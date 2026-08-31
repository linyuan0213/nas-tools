"""SearchOrchestrator — 统一搜索编排器。

合并 Web 搜索、交互式搜索、订阅搜索三条路径的公共逻辑：
关键词解析 → TMDB 识别 → 并发搜索 → Pipeline 过滤 → 去重排序 → 入库 → 可选下载。
所有结果按 session_id 隔离存储，新搜索覆盖旧结果。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any

import log
from app.core.settings import settings
from app.domain.enums import ProgressKey, SearchType, channel_name
from app.domain.interfaces.download_repo import IDownloadHistoryRepository
from app.domain.interfaces.intent import IntentResolver
from app.domain.interfaces.search_repo import ISearchRepository
from app.domain.mediatypes import MediaType
from app.events import Event
from app.events.bus import EventBus
from app.events.constants import SEARCH_START
from app.events.payloads import SearchStartPayload
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.infrastructure.progress import ProgressTracker
from app.media.service import MediaService
from app.message import Message
from app.services.downloader_core import DownloaderCore as Downloader
from app.services.search_context import SearchContext
from app.services.search_service import SearchQueryBuilder, SearchResultDeduplicator, SearchResultProcessor
from app.utils import StringUtils


class SearchOrchestrator:
    def __init__(
        self,
        searcher,  # Searcher
        search_repo: ISearchRepository,
        download_repo: IDownloadHistoryRepository,
        downloader: Downloader,
        media_service: MediaService,
        message: Message,
        progress_helper: ProgressTracker,
        event_bus: EventBus,
        intent_resolver: IntentResolver | None = None,
    ):
        self._searcher = searcher
        self._search_repo = search_repo
        self._download_repo = download_repo
        self._downloader = downloader
        self._media = media_service
        self._message = message
        self._progress = progress_helper
        self._event_bus = event_bus
        self._intent_resolver = intent_resolver
        self._search_auto = settings.get("pt").get("search_auto", True)

    def orchestrate(self, ctx: SearchContext) -> tuple[Any | None, dict | None, int, int]:
        progress_key: str = f"search:{ctx.session_id}"
        self._progress.start(progress_key)

        # 1. 构建搜索词和过滤条件
        search_names, max_workers, filter_args = self._prepare_search(ctx)
        if not search_names:
            self._progress.end(progress_key)
            return None, ctx.no_exists or {}, 0, 0

        # 2. 并发搜索
        media_list = self._execute_searches(ctx, search_names, max_workers, filter_args)

        # 3. 去重
        media_list = SearchResultDeduplicator.deduplicate(media_list)

        if not media_list:
            log.info(f"[Orchestrator]{ctx.keyword} 未搜索到任何资源")
            self._progress.end(progress_key)
            return None, ctx.no_exists or {}, 0, 0

        # 4. 排序（复用 SearchResultProcessor，全系统统一排序键；尊重做种数/站点优先规则）
        self._progress.update(value=85, text=f"排序 {len(media_list)} 条结果...", ptype=progress_key)
        media_list = SearchResultProcessor.sort_results(
            media_list, download_order=(settings.get("pt") or {}).get("download_order")
        )

        # 5. 入库
        if ctx.persist:
            self._enrich_and_persist(ctx, media_list)

        self._progress.update(
            value=100,
            text=f"搜索完成，共 {len(media_list)} 条{self._failed_sites_summary(progress_key)}",
            ptype=progress_key,
        )
        self._progress.end(progress_key)

        # 6. 过滤已下载
        filtered = self._filter_downloaded(media_list)
        if not filtered:
            log.info("[Orchestrator]所有搜索结果已在下载历史中存在")
            return None, ctx.no_exists or {}, len(media_list), 0

        # 7. 择优下载
        if ctx.auto_download and filtered:
            download_items, left_medias = self._downloader.batch_download(
                in_from=ctx.search_type, media_list=filtered, need_tvs=ctx.no_exists, user_name=ctx.user_name
            )
            if download_items:
                total = len(media_list)
                dl_count = len(download_items)
                log.info(f"[Orchestrator]下载了 {dl_count}/{total} 个资源")
                result_no_exists = left_medias if left_medias is not None else (ctx.no_exists or {})
                return download_items[0], result_no_exists, total, dl_count

        return None, ctx.no_exists or {}, len(media_list), 0

    def _prepare_search(self, ctx: SearchContext) -> tuple[list[str], int, dict]:
        media_info = ctx.match_media

        if ctx.filter_args and not media_info:
            return [ctx.keyword], 1, ctx.filter_args

        if not media_info:
            media_info = self._identify_media(ctx)
            ctx.match_media = media_info

        if media_info and media_info.tmdb_info:
            search_names, max_workers = SearchQueryBuilder.build_search_names(media_info, self._media)
            search_season = media_info.get_season_list() if media_info.begin_season is not None else None
            search_episode = media_info.get_episode_list()
            if search_episode and not search_season:
                search_season = [1]
            filter_args = {
                "season": search_season,
                "episode": search_episode,
                "year": media_info.year,
                "type": media_info.type.value if media_info and media_info.type else None,
            }
            if ctx.filter_args:
                filter_args.update(ctx.filter_args)
            return search_names, min(max_workers, 8), filter_args
        else:
            base = {"season": None, "episode": None, "year": None}
            if ctx.filter_args:
                base.update(ctx.filter_args)
            return [ctx.keyword], 1, base

    def _identify_media(self, ctx: SearchContext) -> Any:
        try:
            if self._intent_resolver:
                intent = self._intent_resolver.resolve(ctx.keyword)
                mtype = MediaType.from_string(intent.media_type) if intent.media_type else None
                # TMDB 无动漫类型，识别按电视剧处理（与旧 Web 流水线一致）
                if mtype == MediaType.ANIME:
                    mtype = MediaType.TV
                season_num = intent.season
                episode_num = intent.episode
                keyword = intent.keywords or ctx.keyword
            else:
                mtype, key_word, season_num, episode_num, _year, content = StringUtils.get_keyword_from_string(
                    ctx.keyword
                )
                keyword = content or key_word or ctx.keyword
            if ctx.media_type:
                mtype = ctx.media_type
            ident = self._media.get_media_info(mtype=mtype, title=keyword)
            if ident and ident.tmdb_info:
                if season_num:
                    ident.begin_season = int(season_num)
                if episode_num:
                    ident.begin_episode = int(episode_num)
                log.info(f"[Orchestrator]TMDB 识别: {ident.get_title_string()}")
                return ident
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Orchestrator]TMDB 识别失败: {e}")
        return None

    def _execute_searches(
        self, ctx: SearchContext, search_names: list[str], max_workers: int, filter_args: dict
    ) -> list:
        media_list = []
        progress_key: str = f"search:{ctx.session_id}"
        total = len(search_names)
        # 关键：把 per-session progress_key 注入 filter_args，否则索引器退回全局 key，
        # 站点级进度（"站点搜索 X/Y（站点名）：N 条"）就写不进前端 SSE 可见的会话进度
        filter_args = {**filter_args, "progress_key": progress_key}

        if max_workers <= 1 and total == 1:
            self._progress.update(value=30, text=f"正在搜索: {search_names[0]}", ptype=progress_key)
            result = self._search_one(SearchType.WEB, search_names[0], filter_args, ctx.match_media)
            if result:
                media_list.extend(result)
            self._progress.update(value=80, text=f"搜索完成，找到 {len(media_list)} 条", ptype=progress_key)
            return media_list

        with self._search_executor(max_workers) as executor:
            tasks = []
            for name in search_names:
                tasks.append(executor.submit(self._search_one, SearchType.WEB, name, filter_args, ctx.match_media))

            for idx, future in enumerate(as_completed(tasks), start=1):
                result = future.result()
                pct = 10 + round(70 * (idx / total))
                self._progress.update(value=pct, text=f"搜索关键词 {idx}/{total} 完成", ptype=progress_key)
                if result:
                    if isinstance(result, list):
                        media_list.extend(result)
                    else:
                        media_list.append(result)

        return media_list

    def _search_one(self, in_from: SearchType, key_word: str, filter_args: dict, match_media: Any) -> list:
        if not key_word or not self._searcher.indexer_service:
            return []
        if self._event_bus:
            self._event_bus.publish(
                Event(
                    event_type=SEARCH_START,
                    payload=SearchStartPayload(
                        key_word=key_word,
                        media_info=match_media.to_dict() if match_media else None,
                        filter_args=filter_args,
                        search_type=channel_name(in_from),
                    ),
                )
            )
        return self._searcher.indexer_service.search_by_keyword(
            key_word=key_word, filter_args=filter_args, match_media=match_media, in_from=in_from
        )

    @staticmethod
    def _sort_results(media_list: list) -> list:
        """已归并到 SearchResultProcessor.sort_results，保留以兼容外部调用"""
        return SearchResultProcessor.sort_results(
            media_list, download_order=(settings.get("pt") or {}).get("download_order")
        )

    def _filter_downloaded(self, media_list: list) -> list:
        filtered = []
        for media_item in media_list:
            if media_item.tmdb_id:
                season_episode = media_item.get_season_episode_string()
                if self._download_repo.is_exists_by_tmdb(media_item.tmdb_id, season_episode):
                    log.info(f"[Orchestrator]{media_item.title} {season_episode} 已下载，跳过")
                    continue
            filtered.append(media_item)
        return filtered

    def _enrich_and_persist(self, ctx: SearchContext, media_list: list):
        # 从匹配媒体注入海报/简介/评分到每条搜索结果
        match_media = ctx.match_media
        if match_media:
            poster_url = match_media.get_poster_image()
            overview = match_media.overview
            vote = match_media.vote_average
            for mi in media_list:
                if poster_url and not mi.get_poster_image():
                    mi.poster_path = poster_url
                if overview and not mi.overview:
                    mi.overview = overview
                if vote and not mi.vote_average:
                    mi.vote_average = vote

        self._persist_results(ctx, media_list)

    def _persist_results(self, ctx: SearchContext, media_list: list):
        lock = get_lock_manager().create_lock("search:persist_results", ttl_seconds=60)
        if not lock.acquire():
            log.warn("[Orchestrator]persist 正在执行，跳过")
            return
        try:
            self._search_repo.delete_by_session(ctx.session_id)
            self._search_repo.insert_search_results(
                media_list, ctx.keyword, ctx.ident_flag, ctx.session_id, ctx.user_id
            )
        finally:
            lock.release()

    def _failed_sites_summary(self, progress_key: str) -> str:
        """从搜索进度中汇总失败站点（error/timeout），用于"搜索完成"文本"""
        try:
            detail = self._progress.get_process(progress_key)
            sites = detail.get("sites") if detail else None
            if not sites:
                return ""
            failed = [s for s in sites if s.get("status") in ("error", "timeout")]
            if not failed:
                return ""
            return "；失败站点：" + "、".join(f"{s['name']}({s.get('error') or s['status']})" for s in failed)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Orchestrator]失败站点汇总失败: {e}")
            return ""

    def get_results(self, session_id: str, user_id: str | None = None) -> list:
        if self._search_repo is None:
            return []
        return self._search_repo.get_search_results(session_id, user_id)

    def get_progress(self, session_id: str) -> dict | None:
        session_detail = self._progress.get_process(f"search:{session_id}")
        # session 已结束 → 返回结束状态，防止重新开启
        if session_detail and not session_detail.get("enable") and session_detail.get("value", 0) >= 100:
            return session_detail
        # session 进行中 → 用全局 key 获取 search_by_keyword 内部的详细进度
        global_detail = self._progress.get_process(ProgressKey.Search)
        if global_detail and global_detail.get("enable") and global_detail.get("value", 0) > 0:
            return global_detail
        # 回退到 session key（刚开始/全局 key 还没更新）
        if session_detail and session_detail.get("value", -1) >= 0:
            return session_detail
        return None

    def cleanup_expired_sessions(self, ttl_hours: int = 24):
        self._search_repo.delete_expired(ttl_hours)

    @staticmethod
    @contextmanager
    def _search_executor(max_workers=8):
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="search_orch")
        try:
            yield executor
        finally:
            executor.shutdown(wait=False)
