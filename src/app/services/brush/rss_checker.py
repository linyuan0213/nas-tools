"""Brush RSS checker - RSS 刷流选种逻辑."""

import threading
import time
from typing import Any

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.db.repositories.subscribe_repo_adapter import SubscribeMovieRepositoryAdapter, SubscribeTvRepositoryAdapter
from app.domain.engine.brush_rule_engine import BrushRuleEngine
from app.domain.entities.brush import BrushTaskState
from app.media import MediaService
from app.services.rss_processor import RssHelper
from app.sites import SiteConf
from app.utils import ExceptionUtils, JsonUtils

# 已处理种子缓存 TTL：拒绝原因（优惠/做种人数等）可能随时间变化，过期后允许重新评估
_PROCESSED_CACHE_TTL = 3600


class BrushRssChecker:
    """
    RSS 刷流选种检查器
    职责：解析 RSS、检查选种规则、触发下载。
    """

    def __init__(
        self,
        helper,
        media_service: MediaService,
        sites,
        rsshelper: RssHelper,
        siteconf: SiteConf,
        torrents_cache: dict[str, float] | None = None,
        torrent_lifecycle=None,
    ):
        self._helper = helper
        self._media_service = media_service
        self._rsshelper = rsshelper
        self._sites = sites
        self._siteconf = siteconf
        self._torrents_cache = torrents_cache if torrents_cache is not None else {}
        self._cache_lock = threading.Lock()
        self._torrent_lifecycle = torrent_lifecycle

    def _mark_or_skip_processed(self, task_id: int, enclosure: str) -> bool:
        """标记种子已处理（按任务隔离）；TTL 内已处理过返回 True（跳过）。

        优惠/做种人数等状态可能随时间变化，TTL 过期后放行重新评估。
        缓存键含 task_id，避免任务 A 拒绝的种子影响任务 B。
        """
        cache_key = f"{task_id}:{enclosure}"
        with self._cache_lock:
            now = time.time()
            cached_at = self._torrents_cache.get(cache_key)
            if cached_at is not None and now - cached_at < _PROCESSED_CACHE_TTL:
                return True
            if len(self._torrents_cache) >= 10000:
                oldest = sorted(self._torrents_cache, key=lambda k: self._torrents_cache[k])[:5000]
                for key in oldest:
                    del self._torrents_cache[key]
            self._torrents_cache[cache_key] = now
            return False

    @staticmethod
    def _rss_rule_needs_torrent_attr(rss_rule: dict) -> bool:
        """判断 RSS 选种规则是否需要解析种子详情页属性。"""
        if not rss_rule:
            return False
        for key in ("free", "hr", "peercount", "label_include", "label_exclude"):
            val = rss_rule.get(key)
            if val and val not in ("#", "N", None, ""):
                return True
        return False

    def _check_torrent_attr_if_needed(
        self,
        rss_rule: dict,
        page_url: str | None,
        cookie: str | None,
        api_key: str | None,
        bearer_token: str | None,
        ua: str | None,
        headers: dict,
        site_proxy: bool,
    ) -> dict:
        """仅在规则需要时解析种子详情页属性，避免无意义请求。"""
        if not self._rss_rule_needs_torrent_attr(rss_rule):
            return {}
        if not page_url:
            log.debug("[Brush]page_url 为空，跳过 torrent_attr 检查")
            return {}
        log.debug(f"[Brush]开始检查 torrent_attr, page_url={page_url[:80]}")
        return self._siteconf.check_torrent_attr(
            torrent_url=page_url,
            cookie=cookie,
            api_key=api_key,
            bearer_token=bearer_token,
            ua=ua,
            headers=headers,
            proxy=site_proxy,
        )

    def check_task_rss(self, taskid: int | None, taskinfo: dict) -> None:
        if not taskid or not taskinfo:
            return

        task_name = taskinfo.get("name")
        site_id = taskinfo.get("site_id")
        rss_url = taskinfo.get("rss_url")
        rss_rule = taskinfo.get("rss_rule") or {}
        cookie = taskinfo.get("cookie")
        api_key = taskinfo.get("api_key")
        bearer_token = taskinfo.get("bearer_token")
        rss_free = taskinfo.get("free")
        downloader_id = taskinfo.get("downloader")
        ua = taskinfo.get("ua")
        headers = taskinfo.get("headers")
        if headers and JsonUtils.is_valid_json(headers):
            headers = JsonUtils.loads(headers)
        else:
            headers = {}
        headers.update({"User-Agent": ua})
        if taskinfo.get("state") != BrushTaskState.RUNNING.value:
            log.info(f"[Brush]刷流任务 {task_name} 已停止下载新种！")
            return

        site_info: Any = self._sites.get_sites(siteid=site_id)
        if not site_info:
            log.error(f"[Brush]刷流任务 {task_name} 的站点已不存在，无法刷流！")
            return

        site_id = site_info.get("id")
        site_name = site_info.get("name")
        site_proxy = site_info.get("proxy")
        if not site_info.get("brush_enable"):
            log.error(f"[Brush]站点 {site_name} 未开启刷流功能，无法刷流！")
            return
        if not rss_url:
            log.error(f"[Brush]站点 {site_name} 未配置RSS订阅地址，无法刷流！")
            return
        if rss_free and not (cookie or api_key or bearer_token or taskinfo.get("headers")):
            log.warn(f"[Brush]站点 {site_name} 未配置Cookie、API Key、Bearer Token或请求头，无法开启促销刷流")
            return

        if not self._helper._downloader.get_downloader_conf(downloader_id):
            log.error(f"[Brush]任务 {task_name} 下载器不存在，无法刷流！")
            return

        log.info(f"[Brush]开始站点 {site_name} 的刷流任务：{task_name}...")
        # 先清理已删除的种子记录，避免保种体积虚高阻止进种
        if self._torrent_lifecycle:
            self._torrent_lifecycle.remove_task_torrents(taskid=taskid, taskinfo=taskinfo)
        if not self._helper.is_allow_new_torrent(taskinfo=taskinfo, dlcount=rss_rule.get("dlcount")):
            return

        rss_result = self._rsshelper.parse_rssxml(url=rss_url, proxy=bool(site_proxy))
        if rss_result is None:
            log.error(f"[Brush]{task_name} RSS链接已过期，请重新获取！")
            return
        if len(rss_result) == 0:
            log.warn(f"[Brush]{site_name} RSS未下载到数据")
            return

        max_dlcount = rss_rule.get("dlcount")
        success_count = 0
        new_torrent_count = 0
        if max_dlcount:
            downloading_count = self._helper.get_downloading_count(downloader_id) or 0
            new_torrent_count = int(max_dlcount) - int(downloading_count)

        # 预加载订阅数据（用于 exclude_subscribe 规则）
        rss_movies = None
        rss_tvs = None
        if rss_rule and rss_rule.get("exclude_subscribe") not in ("#", "N", None, ""):
            rss_movies = {
                m.id: {"name": m.name, "year": m.year, "tmdbid": m.tmdbid, "fuzzy_match": m.fuzzy_match}
                for m in SubscribeMovieRepositoryAdapter().get_all(state="R")
            }
            rss_tvs = {
                t.id: {
                    "name": t.name,
                    "year": t.year,
                    "tmdbid": t.tmdbid,
                    "fuzzy_match": t.fuzzy_match,
                    "season": t.season,
                    "rss_sites": t.rss_sites,
                }
                for t in SubscribeTvRepositoryAdapter().get_all(state="R")
            }

        media_service = self._media_service

        for res in rss_result:
            try:
                torrent_name = res.get("title")
                enclosure = res.get("enclosure")
                page_url = res.get("link")
                size = res.get("size")
                pubdate = res.get("pubdate")
                category = res.get("category", "")
                log.debug(
                    f"[Brush]RSS: title={str(torrent_name or '')[:30]}, "
                    f"link={str(page_url or '')[:60]}, enc={str(enclosure or '')[:60]}"
                )

                if not enclosure:
                    continue

                if self._helper.is_torrent_handled(enclosure=enclosure):
                    log.info(f"[Brush]{torrent_name} 已在刷流任务中")
                    continue

                torrent_attr = self._check_torrent_attr_if_needed(
                    rss_rule=rss_rule,
                    page_url=page_url,
                    cookie=cookie,
                    api_key=api_key,
                    bearer_token=bearer_token,
                    ua=ua,
                    headers=headers,
                    site_proxy=bool(site_proxy),
                )

                # 识别媒体信息（用于 exclude_subscribe 规则）
                media_info = None
                if rss_movies is not None or rss_tvs is not None:
                    media_info = media_service.get_media_info(title=torrent_name)

                if not BrushRuleEngine.check_rss_rule(
                    rss_rule=rss_rule,
                    title=torrent_name,
                    torrent_size=size,
                    pubdate=pubdate,
                    torrent_attr=torrent_attr,
                    category=category,
                    labels=torrent_attr.get("labels", ""),
                    media_info=media_info,
                    rss_movies=rss_movies,
                    rss_tvs=rss_tvs,
                ):
                    reject_reason = BrushRuleEngine.get_rss_reject_reason(
                        rss_rule=rss_rule,
                        title=torrent_name,
                        torrent_size=size,
                        pubdate=pubdate,
                        torrent_attr=torrent_attr,
                        category=category,
                        labels=torrent_attr.get("labels", ""),
                        media_info=media_info,
                        rss_movies=rss_movies,
                        rss_tvs=rss_tvs,
                    )
                    if reject_reason:
                        self._helper.log_rejection(
                            taskinfo=taskinfo,
                            torrent_name=torrent_name,
                            reason=f"选种未通过: {reject_reason}",
                            site_name=site_info.get("name", ""),
                            torrent_url=page_url or "",
                        )
                    continue
                if not self._helper.is_allow_new_torrent(taskinfo=taskinfo, dlcount=max_dlcount, torrent_size=size):
                    self._helper.log_rejection(
                        taskinfo=taskinfo,
                        torrent_name=torrent_name,
                        reason="选种未通过: 达到同时下载上限或种数限制",
                        site_name=site_info.get("name", ""),
                        torrent_url=page_url or "",
                    )
                    continue

                if self._helper.download_torrent(
                    taskinfo, rss_rule, site_info, torrent_name, enclosure, size, page_url, torrent_attr
                ):
                    success_count += 1
                    if max_dlcount and success_count >= new_torrent_count:
                        break
                    if not self._helper.is_allow_new_torrent(taskinfo=taskinfo, dlcount=max_dlcount):
                        break
            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                continue
        log.info(f"[Brush]任务 {task_name} 本次添加了 {success_count} 个下载")
