"""Brush helpers - 刷流任务共享辅助方法."""

import ast
import json
import re
import threading
import time
from datetime import datetime
from datetime import time as dtime
from typing import Any
from urllib.parse import urlsplit

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.downloader.registry import get_client_class
from app.infrastructure.cache_system import get_cache_manager
from app.media import meta_info
from app.message import Message
from app.sites import SiteConf
from app.sites.engine import SiteEngine, TorrentAttrFetchError, get_tid_by_url
from app.sites.site_cache import SiteCache
from app.utils import JsonUtils, StringUtils

# 种子详情属性短 TTL 缓存（跨任务/周期共享，走统一缓存系统）：
# 仅缓存“确定结果”（含真实非免费），抓取失败/未知（None）不入缓存，
# 避免把瞬时限流冻结成“非免费”造成误判
_ATTR_CACHE_TTL = 600
_ATTR_CACHE_NAME = "brush_torrent_attr"


def _attr_cache():
    return get_cache_manager().get_or_create(_ATTR_CACHE_NAME, cache_type="memory", maxsize=2000)


def cached_torrent_attr(enclosure: str) -> dict | None:
    """命中且未过期的缓存返回 dict，否则返回 None（None 表示未命中/不缓存）"""
    if not enclosure:
        return None
    return _attr_cache().get(f"attr:{enclosure}")


def store_torrent_attr(enclosure: str, attr: dict | None) -> None:
    """缓存确定结果；attr 为 None（未知/失败）时不缓存"""
    if not enclosure or attr is None:
        return
    _attr_cache().set(f"attr:{enclosure}", attr, ttl=_ATTR_CACHE_TTL)


class BrushTaskHelper:
    """
    刷流任务辅助工具类
    封装 RSS 检查、删种、停种等子流程共享的辅助方法。
    """

    # 下载器级互斥锁（类级共享；download_torrent 锁内重查 dlcount 防并发超额）
    _dl_locks: dict = {}

    def __init__(
        self,
        repo,
        downloader,
        sites: "SiteCache",
        siteconf: SiteConf,
        message: Message,
        site_engine: SiteEngine,
    ):
        self._repo: Any = repo
        self._downloader: Any = downloader
        self._sites = sites
        self._siteconf = siteconf
        self._message: Message = message
        self._site_engine = site_engine
        self._hr_counts: dict[int, int] = {}
        self._dl_stats: dict = {}
        self._dl_locks: dict = {}
        self._deleted_dedup_cache: dict[int, tuple[float, set[str]]] = {}

    def add_hr_count(self, task_id: int) -> None:
        self._hr_counts[task_id] = self._hr_counts.get(task_id, 0) + 1

    def log_rejection(
        self, taskinfo: dict, torrent_name: str, reason: str, site_name: str = "", torrent_url: str = ""
    ) -> None:
        task_id = taskinfo.get("id") or 0
        task_name = taskinfo.get("name") or ""
        self._repo.insert_brush_event(
            task_id=task_id,
            task_name=task_name,
            torrent_name=torrent_name,
            download_id="",
            action="skip",
            reason=reason,
            downloader_name="",
            site_name=site_name,
            torrent_url=torrent_url,
        )

    def _get_downloader_hr_count(self, downloader_id: str, taskinfo: dict) -> int:
        """当前下载器中带 HR 标签的做种种子数（实时统计，不依赖下载器 tag 过滤能力）"""
        try:
            torrents = self._downloader.get_torrents(downloader_id=downloader_id) or []
            return len(
                [t for t in torrents if "HR" in (getattr(t, "labels", None) or []) and getattr(t, "progress", 0) >= 1.0]
            )
        except Exception:
            return 0

    @staticmethod
    def parse_json_rule(val, default=None):
        """安全解析规则字段，兼容 Python 单引号字典格式"""
        if default is None:
            default = {}
        if not val:
            return default
        val = str(val).strip()
        if not val or val in ("''", '""', "'", '"'):
            return default
        try:
            return JsonUtils.loads(val)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except (json.JSONDecodeError, ValueError, TypeError):
            log.debug(f"[Brush]json.loads 解析失败: {val}")
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            inner = val[1:-1]
            try:
                return JsonUtils.loads(inner)
            except (ServiceError, RepositoryError, DomainError):
                raise
            except (json.JSONDecodeError, ValueError, TypeError):
                log.debug(f"[Brush]json.loads 解析失败: {inner}")
            try:
                return JsonUtils.loads(ast.literal_eval(inner))
            except (ServiceError, RepositoryError, DomainError):
                raise
            except (json.JSONDecodeError, ValueError, TypeError):
                log.debug(f"[Brush]json.loads 解析失败: {inner}")
        try:
            return JsonUtils.loads(ast.literal_eval(val))
        except (ServiceError, RepositoryError, DomainError):
            raise
        except (json.JSONDecodeError, ValueError, TypeError):
            log.debug(f"[Brush]json.loads 解析失败: {val}")
        return default

    @staticmethod
    def is_in_active_weekdays(active_weekdays: str = "") -> bool:
        if not active_weekdays or not active_weekdays.strip():
            return True
        try:
            parts = re.split(r"[,\s]+", active_weekdays.strip())
            active_days = {int(p) for p in parts if p}
            today = datetime.now().isoweekday()
            return today in active_days
        except ValueError:
            log.warn("[Brush]活跃星期格式错误，应为逗号分隔的数字 1-7（1=周一）")
            return False

    @staticmethod
    def is_in_time_range(time_range: str = ""):
        if not time_range.strip():
            return True
        try:
            periods = time_range.split(",")
            for period in periods:
                start_str, end_str = period.split("-")
                start_hour, start_minute = map(int, start_str.split(":"))
                end_hour, end_minute = map(int, end_str.split(":"))
                start_time = dtime(start_hour, start_minute)
                end_time = dtime(end_hour, end_minute)
                now = datetime.now().time()
                if start_time < end_time:
                    if start_time <= now <= end_time:
                        return True
                else:
                    if now >= start_time or now <= end_time:
                        return True
            return False
        except ValueError:
            log.warn("[Brush]时间段格式错误，应为 'HH:MM-HH:MM'")
            return False

    def _get_site_engine(self):
        return self._site_engine

    def is_torrent_handled(self, enclosure: str | None, page_url: str | None = None) -> bool:
        if not enclosure and not page_url:
            return False
        engine = self._get_site_engine()
        # 优先用详情页 URL（如 M-Team /detail/{id}）做 tid 去重；
        # RSS enclosure 若为一次性签名链接（sign 每轮变化）直接精确匹配永远不命中。
        dedup_url = page_url or enclosure or ""
        if not dedup_url:
            return False
        if engine.is_tid_based_dedup(dedup_url):
            tid = get_tid_by_url(dedup_url, site_engine=engine)
            if not tid:
                return False
            domain = engine.normalize_domain(dedup_url)
            all_torrents = self._repo.get_brushtask_torrents_by_domain(domain)
            for t in all_torrents:
                record_url = t.PAGE_URL or t.ENCLOSURE or ""
                if get_tid_by_url(record_url, site_engine=engine) == tid:
                    return True
            return False
        return self._repo.get_brushtask_torrent_by_enclosure(enclosure) is not None

    def is_recently_deleted(self, task_id: int | None, page_url: str | None, enclosure: str | None) -> bool:
        """该任务是否近期删除过同一种子（按详情页 tid 判断），避免刷流删种循环重进."""
        if not page_url and not enclosure:
            return False
        task_id = int(task_id or 0)
        if task_id <= 0:
            return False
        cached = self._deleted_dedup_cache.get(task_id)
        if not cached or time.time() - cached[0] > 60:
            deleted_tids: set[str] = set()
            try:
                _, events = self._repo.get_brush_events(task_id, action="delete", page=1, page_size=10000)
                engine = self._get_site_engine()
                for ev in events:
                    url = ev.TORRENT_URL or ""
                    tid = get_tid_by_url(url, site_engine=engine) if url else None
                    if tid:
                        deleted_tids.add(tid)
            except Exception:  # noqa: BLE001
                deleted_tids = set()
            self._deleted_dedup_cache[task_id] = (time.time(), deleted_tids)
        else:
            deleted_tids = cached[1]
        if not deleted_tids:
            return False
        engine = self._get_site_engine()
        target_tid = get_tid_by_url(page_url or enclosure or "", site_engine=engine)
        return bool(target_tid and target_tid in deleted_tids)

    def get_torrent_attr(self, site_info: dict, enclosure: str, use_cache: bool = True):
        if not site_info:
            return None, {}
        ua = site_info.get("ua")
        headers = site_info.get("headers")
        if JsonUtils.is_valid_json(headers):
            headers = JsonUtils.loads(str(headers))
        else:
            headers = {}
        headers.update({"User-Agent": ua})
        site_proxy = site_info.get("proxy")
        site_cookie = site_info.get("cookie")
        split_url = urlsplit(site_info.get("rssurl"))
        site_base_url = f"{split_url.scheme}://{split_url.netloc}"

        engine = self._get_site_engine()
        tid = get_tid_by_url(enclosure, site_engine=engine)
        resolved = engine.resolve_detail_url(enclosure, tid or "")
        # resolve 可能返回相对路径或完整 URL，避免拼接成 base+https:// 的坏链接
        if resolved.startswith(("http://", "https://")):
            torrent_url = resolved
        else:
            torrent_url = f"{site_base_url}{resolved}"

        # 同一详情页短周期内命中缓存（跨任务/周期共享），避免重复抓取。
        # 注意：删种/停种/免费自动恢复等“状态变化敏感”场景需 use_cache=False 取最新态
        if use_cache:
            cached = cached_torrent_attr(torrent_url)
            if cached is not None:
                return torrent_url, cached

        try:
            torrent_attr = self._siteconf.check_torrent_attr(
                torrent_url=torrent_url,
                cookie=site_cookie,
                api_key=site_info.get("api_key"),
                bearer_token=site_info.get("bearer_token"),
                ua=ua,
                headers=headers,
                proxy=bool(site_proxy),
                chrome=bool(site_info.get("chrome")),
                browser_persistent=bool(site_info.get("browser_persistent")),
            )
        except TorrentAttrFetchError as e:
            # 详情抓取失败 → 属性未知（返回 None），调用方不得按“非免费/非HR”误删
            log.warn(f"[Brush]种子属性抓取失败，视为未知: {e}")
            return torrent_url, None
        if use_cache:
            store_torrent_attr(torrent_url, torrent_attr)
        return torrent_url, torrent_attr

    def is_allow_new_torrent(self, taskinfo, dlcount, torrent_size=None):
        if not taskinfo:
            return False
        seed_size = taskinfo.get("seed_size") or None
        time_range = taskinfo.get("time_range") or ""
        active_weekdays = taskinfo.get("active_weekdays") or ""
        task_name = taskinfo.get("name")
        downloader_id = taskinfo.get("downloader")
        downloader_name = taskinfo.get("downloader_name")
        total_size = self._repo.get_brushtask_totalsize(taskinfo.get("id"))

        # 下载器不支持 PT（无法刷流）时禁止新增下载
        if not self._downloader_supports_brush(downloader_id):
            log.warn(f"[Brush]任务 {task_name} 下载器 {downloader_name} 不支持刷流（不适用于 PT 站），暂不添加下载")
            return False

        if torrent_size and seed_size:
            if float(torrent_size) + int(total_size) >= (float(seed_size) + 5) * 1024**3:
                log.warn(
                    f"[Brush]刷流任务 {task_name} 当前保种体积 {round(int(total_size) / (1024**3), 1)}GB，"
                    f"种子大小 {round(int(torrent_size) / (1024**3), 1)}GB，不添加刷流任务"
                )
                return False
        if seed_size:
            if float(seed_size) * 1024**3 <= int(total_size):
                log.warn(
                    f"[Brush]刷流任务 {task_name} 当前保种体积 "
                    f"{round(int(total_size) / 1024 / 1024 / 1024, 1)}GB，不再新增下载"
                )
                return False

        dlstats = self._get_downloader_stats(downloader_id)
        if dlstats is None:
            log.error(f"[Brush]任务 {task_name} 下载器 {downloader_name} 无法连接")
            return False

        if dlcount and int(dlstats["downloading"]) >= int(dlcount):
            log.warn(
                f"[Brush]下载器 {downloader_name} 正在下载任务数：{dlstats['downloading']}，超过设定上限，暂不添加下载"
            )
            return False

        max_seeding = taskinfo.get("max_seeding") or ""
        if max_seeding and max_seeding.isdigit() and int(max_seeding) > 0:
            all_count = dlstats["total"]
            if all_count >= int(max_seeding):
                log.warn(
                    f"[Brush]下载器 {downloader_name} 当前做种数：{all_count}，超过设定上限 {max_seeding}，暂不添加下载"
                )
                return False

        hr_limit = taskinfo.get("hr_limit") or ""
        if hr_limit and hr_limit.isdigit() and int(hr_limit) > 0:
            hr_count = dlstats["hr"]
            if hr_count >= int(hr_limit):
                log.warn(
                    f"[Brush]下载器 {downloader_name} H&R 做种数：{hr_count}，超过设定上限 {hr_limit}，暂不添加下载"
                )
                return False

        if not self.is_in_time_range(time_range=time_range):
            log.warn(f"[Brush]任务 {task_name} 不在所选时间段 {time_range} 内，暂不添加下载")
            return False
        if not self.is_in_active_weekdays(active_weekdays=active_weekdays):
            log.warn(f"[Brush]任务 {task_name} 不在所选活跃星期内，暂不添加下载")
            return False
        return True

    def _downloader_supports_brush(self, downloader_id) -> bool:
        """下载器是否支持刷流（复用 supports_pt 标志）"""
        try:
            conf = self._downloader.get_downloader_conf(downloader_id) or {}
            cls = get_client_class(conf.get("type") or "")
            return bool(getattr(cls, "supports_pt", True)) if cls else False
        except Exception:
            return False

    def _get_downloader_stats(self, downloader_id):
        """下载器种子统计（30s 周期缓存，避免刷流循环内每种子一次全量拉取）.

        返回 {downloading: 未完成数, hr: HR标签做种数, total: 总种子数}，下载器不可达返回 None。
        """
        now = time.time()
        cache_key = f"dl_stats:{downloader_id}"
        cached = self._dl_stats.get(cache_key)
        if cached and now - cached[0] < 30:
            return cached[1]
        try:
            torrents = self._downloader.get_torrents(downloader_id=downloader_id)
        except Exception:
            return None
        if torrents is None:
            return None
        stats = {
            "downloading": len([t for t in torrents if getattr(t, "progress", 0) < 1.0]),
            "hr": len(
                [t for t in torrents if "HR" in (getattr(t, "labels", None) or []) and getattr(t, "progress", 0) >= 1.0]
            ),
            "total": len(torrents),
        }
        self._dl_stats[cache_key] = (now, stats)
        return stats

    def get_downloading_count(self, downloader_id):
        torrents = self._downloader.get_downloading_torrents(downloader_id=downloader_id)
        if torrents is None:
            return None
        return len(torrents)

    def get_downloader_total_count(self, downloader_id):
        torrents = self._downloader.get_torrents(downloader_id=downloader_id)
        return len(torrents) if torrents else 0

    def download_torrent(
        self, taskinfo, rss_rule, site_info, title, enclosure, size, page_url, torrent_attr=None, reason=""
    ):
        if not enclosure:
            return False
        if self._sites.check_ratelimit(site_info.get("id")):
            return False

        taskid = taskinfo.get("id")
        taskname = taskinfo.get("name")
        transfer = taskinfo.get("transfer")
        sendmessage = taskinfo.get("sendmessage")
        downloader_id = taskinfo.get("downloader")
        download_limit = rss_rule.get("downspeed")
        upload_limit = rss_rule.get("upspeed")
        download_dir = taskinfo.get("savepath")

        hr_tag = []
        hr_rule = (rss_rule.get("hr") or "").strip()
        # 与选种一致：#/N/空 表示"不限 HR"，此时不抓详情、不因抓取失败阻断下载（多数站点无 HR）
        if hr_rule and hr_rule not in ("#", "N"):
            if not torrent_attr:
                _, torrent_attr = self.get_torrent_attr(site_info, enclosure)
            if torrent_attr is None:
                # HR 属性未知（抓取失败）：不冒 HR 风险下载
                log.warn(f"[Brush]{title} HR 属性未知（详情抓取失败），暂停下载")
                return False
            if torrent_attr.get("hr"):
                hr_tag = ["HR"]
        tag = taskinfo.get("label").split(",") if taskinfo.get("label") else []
        if not transfer:
            tag = tag + ["已整理"] + hr_tag if tag else ["已整理"] + hr_tag

        mi = meta_info(title=title)
        mi.set_torrent_info(site=site_info.get("name"), enclosure=enclosure, size=size)
        # 下载器级互斥：锁内重查 dlcount（防多任务共享下载器时并发超额），再执行下载
        dl_lock = self._dl_locks.setdefault(str(downloader_id), threading.Lock())
        with dl_lock:
            dlcount = rss_rule.get("dlcount")
            if dlcount:
                stats = self._get_downloader_stats(downloader_id)
                if stats is None:
                    log.error(f"[Brush]{taskname} 下载器 {downloader_id} 无法连接，跳过下载")
                    return False
                if stats["downloading"] >= int(dlcount):
                    log.warn(f"[Brush]{taskname} 下载器 {downloader_id} 下载中任务数达上限 {dlcount}，跳过下载")
                    return False
            _, download_id, retmsg = self._downloader.download(
                media_info=mi,
                tag=tag,
                downloader_id=downloader_id,
                download_dir=download_dir,
                download_setting="-2",
                download_limit=download_limit,
                upload_limit=upload_limit,
            )
        if not download_id:
            if retmsg:
                log.warn(f"[Brush]{taskname} 添加下载任务出错：{title}，错误原因：{retmsg}，种子链接：{enclosure}")
                return False
            log.info(f"[Brush]{title} 已存在于下载器中，记录进种")
        else:
            log.info(f"[Brush]成功添加下载：{title}")

        downloader_cfg = self._downloader.get_downloader_conf(downloader_id)
        downlaod_name = downloader_cfg.get("name") if downloader_cfg else ""

        if not reason:
            reason = BrushRuleEngine.format_rss_match_reason(rss_rule)
        torrent_status = []
        attr = torrent_attr or {}
        if attr.get("free"):
            torrent_status.append("免费")
        if attr.get("2xfree"):
            torrent_status.append("2X免费")
        if attr.get("hr"):
            torrent_status.append("HR")
        if attr.get("peer_count"):
            torrent_status.append(f"做种{attr['peer_count']}")
        if size:
            try:
                size_num = int(float(size))
            except (ValueError, TypeError):
                size_num = 0
            if size_num > 0:
                torrent_status.append(StringUtils.str_filesize(size_num))
        if not torrent_status:
            m = re.search(r"\[(\d+\.?\d*\s*(?:GB|MB|TB|KB))\]", title)
            if m:
                torrent_status.append(m.group(1))

        if not torrent_status and not reason:
            reason = "RSS 进种"
        if torrent_status:
            reason = f"{reason} | 状态: {', '.join(torrent_status)}"

        self._repo.insert_brush_event(
            task_id=taskid or 0,
            task_name=taskname or "",
            torrent_name=title,
            download_id=download_id or "",
            action="download",
            reason=reason,
            downloader_name=downlaod_name,
            site_name=site_info.get("name", ""),
            torrent_url=page_url or "",
        )
        if sendmessage:
            msg_title = f"[刷流任务 {taskname} 新增下载]"
            msg_text = (
                f"下载器名：{downlaod_name}\n"
                f"种子名称：{title}\n"
                f"种子大小：{StringUtils.str_filesize(size)}\n"
                f"添加时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
            )
            self._message.send_brushtask_added_message(title=msg_title, text=msg_text)

        if download_id:
            if self._repo.insert_brushtask_torrent(
                brush_id=taskid,
                title=title,
                enclosure=enclosure,
                downloader=downloader_id,
                download_id=download_id,
                size=size,
                page_url=page_url or "",
            ):
                self._repo.add_brushtask_download_count(brush_id=taskid)
            else:
                log.info(f"[Brush]{title} 已下载过")
        else:
            # 种子已存在于下载器但未能获取种子ID（如 qb 重复添加），无法跟踪则不入库
            log.warn(f"[Brush]{title} 已存在于下载器但未能获取种子ID，跳过记录")
        return True
