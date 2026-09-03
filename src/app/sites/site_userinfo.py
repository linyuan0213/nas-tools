import base64
import time
from concurrent.futures import as_completed
from datetime import datetime
from threading import Lock
from typing import Any

import log
from app.db.models import SITEUSERINFOSTATS as _S
from app.db.repositories.site_repo_adapter import SiteRepositoryAdapter
from app.db.repositories.site_repository import SiteRepository
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.infrastructure.http import CookieAuth, HttpClient, HttpClientConfig
from app.infrastructure.rate_limiter import MemoryTokenBucketBackend, RateLimitEngine
from app.infrastructure.thread import ThreadExecutor
from app.message import Message
from app.message.web_store import WebMessageStore
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.sites.site_favicon_service import SiteFaviconService
from app.utils import ExceptionUtils, JsonUtils, StringUtils
from app.utils.browser_mode import build_browser_mode
from app.utils.config_tools import get_proxies

lock = Lock()


def _log_error(site_name):
    log.error(f"[Sites]站点 {site_name} 无法识别站点类型")


class SiteUserInfo:
    sites = None
    message = None

    _MAX_CONCURRENCY = 10
    _SITE_REFRESH_RATE = "1/s"
    _SITE_REFRESH_BURST = 1
    _last_update_time = None
    _sites_data = {}

    def __init__(
        self,
        site_cache: SiteCache,
        site_repository: SiteRepository,
        site_favicon_service: SiteFaviconService,
        site_engine: SiteEngine,
        message: Message | None = None,
        thread_executor: ThreadExecutor | None = None,
        rate_limiter: RateLimitEngine | None = None,
    ):
        self._site_cache = site_cache
        self._site_repository = site_repository
        self._site_favicon_service = site_favicon_service
        self._site_engine = site_engine
        self._message = message
        self._thread_executor = thread_executor or ThreadExecutor(
            max_workers=self._MAX_CONCURRENCY, name="site_refresh"
        )
        self._rate_limiter = rate_limiter or RateLimitEngine(backend=MemoryTokenBucketBackend())
        self._refresh()

    def _refresh(self):
        self.sites = self._site_cache
        self.site_repo = SiteRepositoryAdapter(self._site_repository)
        self.message = self._message
        # 站点上一次更新时间
        self._last_update_time = None
        # 站点数据
        self._sites_data = {}

    def _refresh_site_data_with_limit(self, site_info: dict) -> Any:
        """带站点级限流的单个站点刷新包装."""
        site_name = site_info.get("name") or "unknown"
        site_id = site_info.get("id")
        acquired = self._rate_limiter.acquire(
            key=f"site_refresh:{site_id or site_name}",
            rate=self._SITE_REFRESH_RATE,
            burst=self._SITE_REFRESH_BURST,
            timeout=0,
        )
        if not acquired:
            log.warn(f"[Sites]站点 {site_name} 刷新被限流跳过")
            return None
        return self._refresh_site_data(site_info)

    def _refresh_site_data(self, site_info: dict) -> Any:
        """
        更新单个site 数据信息
        :param site_info:
        :return:
        """
        site_id = site_info.get("id")
        site_name = site_info.get("name")
        site_url = site_info.get("strict_url")
        if not site_url:
            return
        site_cookie = site_info.get("cookie")
        api_key = site_info.get("api_key")
        bearer_token = site_info.get("bearer_token")
        ua = site_info.get("ua")
        headers = site_info.get("headers") or ""
        if JsonUtils.is_valid_json(headers):
            headers = JsonUtils.loads(headers)
        else:
            headers = {}
        unread_msg_notify = site_info.get("unread_msg_notify")
        chrome = bool(site_info.get("chrome"))
        proxy = bool(site_info.get("proxy"))
        try:
            site_user_info = self.build(
                url=site_url,
                site_id=site_id,
                site_name=site_name,
                site_cookie=site_cookie,
                ua=ua,
                site_headers=headers,
                emulate=chrome,
                proxy=proxy,
                api_key=api_key,
                bearer_token=bearer_token,
                browser_persistent=bool(site_info.get("browser_persistent")),
            )
            if site_user_info:
                log.debug(f"[Sites]站点 {site_name} 开始以 {site_user_info.site_schema()} 模型解析")
                # 开始解析
                site_user_info.parse()
                log.debug(f"[Sites]站点 {site_name} 解析完成")

                if not site_user_info.site_favicon:
                    site_def = self._site_engine.get_by_url(site_url)
                    if site_def and site_def.favicon:
                        site_user_info.site_favicon = site_def.favicon

                # 获取不到数据时，仅返回错误信息，不做历史数据更新
                if site_user_info.err_msg:
                    self._sites_data.update({site_name: {"err_msg": site_user_info.err_msg}})
                    return

                # 发送通知，存在未读消息
                self._notify_unread_msg(site_name, site_user_info, unread_msg_notify)

                self._sites_data.update(
                    {
                        site_name: {
                            "upload": site_user_info.upload,
                            "username": site_user_info.username,
                            "user_level": site_user_info.user_level,
                            "join_at": site_user_info.join_at,
                            "download": site_user_info.download,
                            "ratio": site_user_info.ratio,
                            "seeding": site_user_info.seeding,
                            "seeding_size": site_user_info.seeding_size,
                            "leeching": site_user_info.leeching,
                            "bonus": site_user_info.bonus,
                            "url": site_url,
                            "err_msg": site_user_info.err_msg,
                            "message_unread": site_user_info.message_unread,
                        }
                    }
                )

                return site_user_info

        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"[Sites]站点 {site_name} 获取流量数据失败：{e!s}")

    def build(
        self,
        url,
        site_id,
        site_name,
        site_cookie=None,
        site_headers=None,
        ua=None,
        emulate=None,
        proxy=False,
        api_key=None,
        bearer_token=None,
        browser_persistent=False,
    ):
        if not site_cookie and not site_headers and not api_key and not bearer_token:
            return None
        if site_headers is None:
            return None
        log.debug(f"[Sites]站点 {site_name} url={url}")

        if self.sites is None:
            return
        if self.sites.check_ratelimit(site_id):
            return

        site_headers.update({"User-Agent": ua, "referer": url})

        engine = self._site_engine
        site_def = engine.get_by_url(url)

        if site_def and site_def.user_info and site_def.user_info.get("profile"):
            return engine.get_user_info(
                url,
                site_name,
                site_cookie,
                html_text=None,
                site_headers=site_headers,
                ua=ua or "",
                emulate=emulate or False,
                proxy=proxy,
                api_key=api_key,
                bearer_token=bearer_token,
                browser_persistent=browser_persistent,
            ) or _log_error(site_name)

        html_text = None
        proxies = get_proxies() if proxy else None
        proxy_url = proxies.get("http") if proxies else None
        rate_limiter = getattr(engine, "site_limiter", None)
        rate_limiter_engine = rate_limiter.engine if rate_limiter else None
        rl_kwargs = {}
        if rate_limiter and site_id:
            rate_config = rate_limiter.get_rate(str(site_id))
            if rate_config:
                rl_kwargs = {"rate_limit_key": f"site:{site_id}", "rate_limit_rate": rate_config[0]}
        browser = build_browser_mode(
            site_info={"chrome": emulate, "ua": ua, "browser_render": False},
            site_key=site_name or url,
            proxy_url=proxy_url,
            render_html=False,
        )
        client = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url, browser=browser),
            rate_limiter=rate_limiter_engine,
        )
        res = client.get(url=url, headers=site_headers, auth=CookieAuth(site_cookie), **rl_kwargs)
        if res.status_code == 200:
            html_text = res.text
        else:
            log.error(f"[Sites]站点 {site_name} 无法访问：{url}")
            return None

        return engine.get_user_info(
            url,
            site_name,
            site_cookie,
            html_text=html_text,
            site_headers=site_headers,
            ua=ua or "",
            emulate=emulate or False,
            proxy=proxy,
            api_key=api_key,
            bearer_token=bearer_token,
            browser_persistent=browser_persistent,
        ) or _log_error(site_name)

    def _notify_unread_msg(self, site_name, site_user_info, unread_msg_notify):
        if self.message is None:
            return
        if site_user_info.message_unread <= 0:
            return
        if self._sites_data.get(site_name, {}).get("message_unread") == site_user_info.message_unread:
            return
        if not unread_msg_notify:
            return

        # 解析出内容，则发送内容
        if len(site_user_info.message_unread_contents) > 0:
            for head, date, content in site_user_info.message_unread_contents:
                msg_title = f"[站点 {site_user_info.site_name} 消息]"
                msg_text = f"时间：{date}\n标题：{head}\n内容：\n{content}"
                self.message.send_site_message(title=msg_title, text=msg_text)
        else:
            self.message.send_site_message(
                title=f"站点 {site_user_info.site_name} 收到 {site_user_info.message_unread} 条新消息，请登陆查看"
            )

    def refresh_site_data_now(self, specify_sites=None):
        """
        强制刷新站点数据
        :param specify_sites: 指定站点名称列表，None 表示全部
        """
        lock_key = f"site:refresh:{','.join(specify_sites) if specify_sites else 'all'}"

        refresh_lock = get_lock_manager().create_lock(lock_key, ttl_seconds=600)
        acquired = refresh_lock.acquire()
        if not acquired:
            log.info("[Sites]站点数据刷新正在执行，跳过")
            return
        try:
            self.__refresh_all_site_data(force=True, specify_sites=specify_sites)
        finally:
            refresh_lock.release()
        # 刷完发送消息
        string_list = []

        # 增量数据
        inc_uploads = 0
        inc_downloads = 0
        _, _, site, upload, download = self.get_pt_site_statistics_history(2)

        # 按照上传降序排序
        data_list = list(zip(site, upload, download, strict=False))
        data_list = sorted(data_list, key=lambda x: x[1], reverse=True)

        for data in data_list:
            site = data[0]
            upload = int(data[1])
            download = int(data[2])
            if upload > 0 or download > 0:
                inc_uploads += int(upload)
                inc_downloads += int(download)
                string_list.append(
                    f"[{site}]\n"
                    f"上传量：{StringUtils.str_filesize(upload)}\n"
                    f"下载量：{StringUtils.str_filesize(download)}\n"
                    f"\n————————————"
                )

        if inc_downloads or inc_uploads:
            if self.message is None:
                return
            msg_text = "\n".join(string_list)
            # 内容与最近一次已发送的一致（如重启/重复刷新）则跳过，避免产生重复统计消息
            if self._stats_message_unchanged(msg_text):
                log.info("[Sites]站点数据统计无变化，跳过重复发送")
                return
            self.message.send_user_statistics_message(string_list)

    def _stats_message_unchanged(self, msg_text: str) -> bool:
        """统计消息内容是否与最近一次已发送（持久化）的一致"""
        try:
            items = WebMessageStore.instance().history(user_id="", limit=20)
            for item in reversed(items):
                if (item.get("title") or "").strip() == "站点数据统计":
                    return (item.get("content") or "").strip() == msg_text.strip()
        except Exception as e:
            log.debug(f"[Sites]统计消息去重检查失败: {e}")
        return False

    def refresh_site_data(self, force=False, specify_sites=None) -> dict:
        """
        刷新站点数据，返回站点数据字典
        :param force: 是否强制刷新
        :param specify_sites: 指定站点名称列表
        :return: 站点数据字典
        """
        self.__refresh_all_site_data(force=force, specify_sites=specify_sites)
        return self._sites_data

    def __refresh_all_site_data(self, force=False, specify_sites=None):
        """
        多线程刷新站点下载上传量，默认间隔6小时

        锁只保护竞争条件检查和 _last_update_time 写入，ThreadPool 和
        HTTP 请求在锁外执行，避免阻塞索引器搜索等其他线程。
        """
        if self.sites is None:
            return

        if specify_sites and not isinstance(specify_sites, list):
            specify_sites = [specify_sites]

        # 锁只保护竞争条件检查和 _last_update_time 写入
        with lock:
            if not force and not specify_sites and self._last_update_time:
                return
            self._last_update_time = datetime.now()

        if not self.sites.get_sites():
            return

        # 没有指定站点，默认使用全部站点
        if not specify_sites:
            refresh_sites = self.sites.get_sites(statistic=True)
        else:
            refresh_sites = [site for site in self.sites.get_sites(statistic=True) if site.get("name") in specify_sites]

        if not refresh_sites:
            return

        # 按站点名称去重，避免同一站点被并行刷新多次导致数据库冲突
        seen_names = set()
        unique_sites = []
        for site in refresh_sites:
            name = site.get("name")
            if name and name not in seen_names:
                seen_names.add(name)
                unique_sites.append(site)
        refresh_sites = unique_sites

        # 锁只保护竞争条件检查和状态写入，不包含 IO 密集型操作
        with lock:
            if not force and not specify_sites and self._last_update_time:
                return
            self._last_update_time = datetime.now()

        # 使用 ThreadExecutor + 站点级限流并发刷新
        futures = []
        for site in refresh_sites:
            futures.append(self._thread_executor.submit(self._refresh_site_data_with_limit, site))

        site_user_infos = []
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    site_user_infos.append(result)
            except Exception as e:
                log.warn("[Sites]站点刷新任务异常")
                ExceptionUtils.exception_traceback(e)

        # 结果处理也在锁外
        log.debug(f"[Sites]开始写入数据库，共 {len(site_user_infos)} 个站点")
        t0 = time.time()
        self.site_repo.insert_site_statistics_history(site_user_infos)
        log.debug(f"[Sites]insert_site_statistics_history 耗时 {time.time() - t0:.2f}s")
        t0 = time.time()
        self.site_repo.update_site_user_statistics(site_user_infos)
        log.debug(f"[Sites]update_site_user_statistics 耗时 {time.time() - t0:.2f}s")
        t0 = time.time()
        self.site_repo.update_site_favicon(site_user_infos)
        log.debug(f"[Sites]update_site_favicon 耗时 {time.time() - t0:.2f}s")
        t0 = time.time()
        self.site_repo.update_site_seed_info(site_user_infos)
        log.debug(f"[Sites]update_site_seed_info 耗时 {time.time() - t0:.2f}s")
        t0 = time.time()
        self._site_favicon_service.refresh()
        log.debug(f"[Sites]init_favicons 耗时 {time.time() - t0:.2f}s")

    def get_pt_site_statistics_history(self, days=7, end_day=None):
        """
        获取站点上传下载量
        """
        if self.sites is None:
            return 0, 0, [], [], []
        site_urls = []
        for site in self.sites.get_sites(statistic=True):
            site_url = site.get("strict_url")
            if site_url:
                site_urls.append(site_url)

        return self.site_repo.get_site_statistics_recent_sites(days=days, end_day=end_day, strict_urls=site_urls)

    def get_site_user_statistics(self, sites=None, encoding="RAW") -> Any:
        """
        获取站点用户数据
        :param sites: 站点名称
        :param encoding: RAW/DICT
        :return:
        """
        if self.sites is None:
            return []
        statistic_sites = self.sites.get_sites()
        if not sites:
            site_urls = [site.get("strict_url") for site in statistic_sites]
        else:
            site_urls = [site.get("strict_url") for site in statistic_sites if site.get("name") in sites]

        raw_statistics = list(self.site_repo.get_site_user_statistics(strict_urls=site_urls))
        existing_urls = {s.URL for s in raw_statistics if str(s.URL)}
        url_to_pri = {s.get("strict_url"): s.get("pri", 0) for s in statistic_sites}
        for site in statistic_sites:
            url = site.get("strict_url")
            if url and url not in existing_urls:
                raw_statistics.append(
                    _S(
                        SITE=site.get("name") or "",
                        URL=url,
                        USERNAME="",
                        USER_LEVEL="",
                        JOIN_AT="",
                        UPDATE_AT="",
                        UPLOAD=0,
                        DOWNLOAD=0,
                        RATIO=0,
                        SEEDING=0,
                        LEECHING=0,
                        SEEDING_SIZE=0,
                        BONUS=0,
                    )
                )
        raw_statistics.sort(key=lambda s: url_to_pri.get(s.URL, 0))
        if encoding == "RAW":
            return raw_statistics

        return self.__todict(raw_statistics)

    def get_pt_site_activity_history(self, site, days=365 * 2):
        """
        查询站点 上传，下载，做种数据
        :param site: 站点名称
        :param days: 最大数据量
        :return:
        """
        site_activities: list = [["time", "upload", "download", "bonus", "seeding", "seeding_size"]]
        sql_site_activities = self.site_repo.get_site_statistics_history(site=site, days=days)
        for sql_site_activity in sql_site_activities:
            timestamp = datetime.strptime(str(sql_site_activity.DATE), "%Y-%m-%d").timestamp() * 1000
            site_activities.append(
                [
                    timestamp,
                    int(str(sql_site_activity.UPLOAD or 0)),
                    int(str(sql_site_activity.DOWNLOAD or 0)),
                    float(str(sql_site_activity.BONUS or 0)),
                    int(str(sql_site_activity.SEEDING or 0)),
                    int(str(sql_site_activity.SEEDING_SIZE or 0)),
                ]
            )

        return site_activities

    def get_pt_site_seeding_info(self, site):
        """
        查询站点 做种分布信息
        :param site: 站点名称
        :return: seeding_info:[uploader_num, seeding_size]
        """
        site_seeding_info = {"seeding_info": []}
        seeding_info = self.site_repo.get_site_seeding_info(site=site)
        if not seeding_info:
            return site_seeding_info

        site_seeding_info["seeding_info"] = JsonUtils.loads(seeding_info[0])
        return site_seeding_info

    def get_pt_site_min_join_date(self, sites=None):
        """
        查询站点加入时间
        """
        statistics = self.get_site_user_statistics(sites=sites, encoding="DICT")
        if not statistics:
            return ""
        dates = []
        for s in statistics:
            if s.get("join_at"):
                try:
                    dates.append(datetime.strptime(s.get("join_at"), "%Y-%m-%d %H:%M:%S"))
                except Exception as err:
                    log.warn(f"[SiteUserInfo]解析加入时间失败: {err}")
        if dates:
            return min(dates).strftime("%Y-%m-%d")
        return ""

    def _fetch_favicon_from_url(self, site_user_info, url, ua=""):
        try:
            engine = self._site_engine
            rate_limiter = getattr(engine, "site_limiter", None)
            rate_limiter_engine = rate_limiter.engine if rate_limiter else None
            client = HttpClient(
                config=HttpClientConfig(),
                rate_limiter=rate_limiter_engine,
            )
            res = client.get(url=url, headers={"User-Agent": ua or "Mozilla/5.0"})
            site_user_info.site_favicon = base64.b64encode(res.content).decode()
        except Exception as e:  # noqa: BLE001
            log.debug(f"[SiteUserInfo]忽略异常: {e}")

    @staticmethod
    def __format_filesize(size_bytes):
        """将字节转换为人类可读字符串，与前端 parseSize 兼容"""
        if size_bytes is None or size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        val = float(size_bytes)
        while val >= 1024 and idx < len(units) - 1:
            val /= 1024
            idx += 1
        return f"{val:.2f} {units[idx]}"

    @staticmethod
    def __todict(raw_statistics):
        statistics = []
        for site in raw_statistics:
            ratio_val = site.RATIO
            ratio_str = f"{ratio_val:.2f}" if ratio_val is not None else "0.00"
            bonus_val = site.BONUS
            bonus_str = f"{bonus_val:.2f}" if bonus_val is not None else "0.00"
            statistics.append(
                {
                    "site_name": site.SITE or "",
                    "username": site.USERNAME or "",
                    "user_level": site.USER_LEVEL or "",
                    "join_at": site.JOIN_AT or "",
                    "update_at": site.UPDATE_AT or "",
                    "upload": SiteUserInfo.__format_filesize(site.UPLOAD),
                    "download": SiteUserInfo.__format_filesize(site.DOWNLOAD),
                    "ratio": ratio_str,
                    "seeding_count": site.SEEDING or 0,
                    "leeching_count": site.LEECHING or 0,
                    "seeding_size": SiteUserInfo.__format_filesize(site.SEEDING_SIZE),
                    "bonus": bonus_str,
                    "url": site.URL or "",
                    "message_count": site.MSG_UNREAD or 0,
                }
            )
        return statistics

    def update_site_name(self, old_name, name):
        """
        更新站点数据中的站点名称
        """
        self.site_repo.update_site_user_statistics_site_name(name, old_name)
        self.site_repo.update_site_seed_info_site_name(name, old_name)
        self.site_repo.update_site_statistics_site_name(name, old_name)
        return True
