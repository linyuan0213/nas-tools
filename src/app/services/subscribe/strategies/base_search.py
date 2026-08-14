"""基础搜索策略 — 提取 subscribe_search_engine 公共逻辑."""

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import log
from app.core.exceptions import (
    DownloadError,
    IndexerError,
    MediaError,
    NetworkError,
    RepositoryError,
    ServiceError,
)
from app.db.repositories.subscribe_repo_adapter import (
    SubscribeMovieRepositoryAdapter,
    SubscribeTvEpisodeRepositoryAdapter,
    SubscribeTvRepositoryAdapter,
)
from app.db.repositories.subscribe_repository import SubscribeRepository
from app.domain.entities.rss import SubscribeState
from app.domain.enums import SearchType, SystemConfigKey
from app.domain.interfaces.rss_repo import (
    ISubscribeMovieRepository,
    ISubscribeTvEpisodeRepository,
    ISubscribeTvRepository,
)
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import get_cache_manager
from app.media import MediaCache, MediaService, meta_info
from app.message import Message
from app.services.downloader_core import DownloaderCore as Downloader
from app.services.filter_service import FilterService as Filter
from app.services.search_service import Searcher
from app.services.subscribe.coordinator import DownloadCoordinator
from app.sites.torrent import Torrent


class BaseSearchStrategy:
    """搜索策略基类 — 封装 movie/tv 的公共搜索/下载逻辑."""

    _movie_repo: ISubscribeMovieRepository
    _tv_repo: ISubscribeTvRepository
    _tv_episode_repo: ISubscribeTvEpisodeRepository

    LOCK_EXTEND_INTERVAL = 60

    def __init__(
        self,
        service: Any,
        searcher: Searcher,
        media_service: MediaService,
        media_cache: MediaCache,
        downloader: Downloader,
        filter_service: Filter,
        message: Message,
        rss_repo: SubscribeRepository | None = None,
        movie_repo: ISubscribeMovieRepository | None = None,
        tv_repo: ISubscribeTvRepository | None = None,
        tv_episode_repo: ISubscribeTvEpisodeRepository | None = None,
        coordinator: DownloadCoordinator | None = None,
        system_config=None,
    ):
        self._service = service
        self._system_config = system_config
        self._rss_repo = rss_repo or SubscribeRepository()
        if movie_repo is None:
            movie_repo = SubscribeMovieRepositoryAdapter(self._rss_repo)
        if tv_repo is None:
            tv_repo = SubscribeTvRepositoryAdapter(self._rss_repo)
        if tv_episode_repo is None:
            tv_episode_repo = SubscribeTvEpisodeRepositoryAdapter(self._rss_repo)
        self._movie_repo = movie_repo
        self._tv_repo = tv_repo
        self._tv_episode_repo = tv_episode_repo

        self._searcher = searcher
        self._coordinator = coordinator
        self._media_service = media_service
        self._media_cache = media_cache
        self._downloader = downloader
        self._filter = filter_service
        self._message = message
        self._ident_cache = get_cache_manager().get_or_create(
            "subscribe_ident", cache_type="memory", maxsize=1000, ttl=3600
        )

    def set_coordinator(self, coordinator: DownloadCoordinator | None) -> None:
        """设置下载协调器（用于 SubscriptionMonitor 注入）."""
        self._coordinator = coordinator

    def search_pending(self) -> None:
        """触发一次队列搜索（处理 PENDING 订阅），供事件处理器调用."""
        self._search_movies(state=SubscribeState.PENDING.value)
        self._search_tvs(state=SubscribeState.PENDING.value)

    def search_retry(self) -> None:
        """重试 ERROR 状态的订阅."""
        self._search_movies(state=SubscribeState.ERROR.value)
        self._search_tvs(state=SubscribeState.ERROR.value)

    def _get_effective_search_sites(self, rss_info: dict, mtype: MediaType) -> list:
        """订阅未配置搜索站点时，回退到默认订阅设置的 search_sites（空则不搜索）"""
        sites = rss_info.get("search_sites") or []
        if sites:
            return sites
        if not self._system_config:
            return []
        try:
            default_setting = self._system_config.get(
                SystemConfigKey.DefaultSubscribeSettingTV
                if mtype in (MediaType.TV, MediaType.ANIME)
                else SystemConfigKey.DefaultSubscribeSettingMOV
            )
            if not isinstance(default_setting, dict):
                return []
            return default_setting.get("search_sites") or []
        except Exception as e:
            log.debug(f"[Subscribe]读取默认订阅设置站点失败: {e}")
            return []

    @contextmanager
    def _lock_context(self, media_info):
        """持锁期间自动续期，并在退出时释放锁。"""
        if self._coordinator is None or media_info is None:
            yield
            return

        stop_event = threading.Event()

        def _extend_loop():
            while not stop_event.wait(self.LOCK_EXTEND_INTERVAL):
                try:
                    if self._coordinator is not None:
                        self._coordinator.extend(media_info)
                except Exception as e:
                    log.debug(f"[BaseSearchStrategy] 锁续期失败: {e}")

        thread = threading.Thread(target=_extend_loop, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            self._coordinator.release(media_info)

    def _search_movies(self, state: str = SubscribeState.PENDING.value, rssid: int | None = None) -> None:
        if rssid:
            rss_movies = self._service.get_subscribe_movies(rid=rssid) if self._service else {}
        else:
            rss_movies = self._service.get_subscribe_movies(state=state) if self._service else {}
        if not rss_movies:
            return
        log.info(f"[Subscribe]共有 {len(rss_movies)} 个{MediaType.MOVIE.display_name}订阅需要搜索")

        def _process_one(rss_info: dict) -> None:
            if rss_info.get("fuzzy_match"):
                return
            rid = rss_info.get("id")
            name_val = rss_info.get("name")
            year_val = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")
            over_edition = rss_info.get("over_edition")
            keyword = rss_info.get("keyword")

            media_info = None
            try:
                media_info = self._get_media_info(tmdbid, name_val, year_val, MediaType.MOVIE)
                if not media_info or not media_info.tmdb_info:
                    log.warn(f"[Subscribe]{MediaType.MOVIE.display_name} {name_val} TMDB 识别失败，标记为错误状态")
                    self._movie_repo.update_state(title=None, year=None, rssid=rid, state=SubscribeState.ERROR.value)
                    return

                media_info.set_download_info(
                    download_setting=rss_info.get("download_setting"), save_path=rss_info.get("save_path")
                )
                media_info.keyword = keyword

                if self._coordinator and not self._coordinator.try_acquire(media_info):
                    log.info(f"[Subscribe]{MediaType.MOVIE.display_name} {name_val} 已被其他策略处理，跳过")
                    self._movie_repo.update_state(title=None, year=None, rssid=rid, state=SubscribeState.RUNNING.value)
                    return

                with self._lock_context(media_info):
                    if not over_edition:
                        exist_flag, no_exists, _ = self._downloader.check_exists_medias(meta_info=media_info)
                        if exist_flag:
                            log.info(
                                f"[Subscribe]{MediaType.MOVIE.display_name} {media_info.get_title_string()} 已存在"
                            )
                            if self._service:
                                self._service.finish_rss_subscribe(rssid=rid, media=media_info)
                            return
                    else:
                        no_exists = {}
                        media_info.over_edition = over_edition
                        if rid is not None:
                            media_info.res_order = self._movie_repo.get_filter_order(rssid=rid)

                    self._movie_repo.update_state(
                        title=None, year=None, rssid=rid, state=SubscribeState.SEARCHING.value
                    )

                    try:
                        filters = {
                            "restype": rss_info.get("filter_restype"),
                            "pix": rss_info.get("filter_pix"),
                            "team": rss_info.get("filter_team"),
                            "rule": rss_info.get("filter_rule"),
                            "include": rss_info.get("filter_include"),
                            "exclude": rss_info.get("filter_exclude"),
                            "free": rss_info.get("filter_free"),
                            "site": rss_info.get("search_sites"),
                        }
                        search_result, _, _, _ = self._searcher.search_one_media(
                            media_info=media_info,
                            in_from=SearchType.SUBSCRIBE,
                            no_exists=no_exists,
                            sites=self._get_effective_search_sites(rss_info, MediaType.MOVIE),
                            filters=filters,
                        )
                        if search_result:
                            if over_edition:
                                if self._service:
                                    self._service.update_subscribe_over_edition(
                                        rtype=search_result.type, rssid=rid, media=search_result
                                    )
                            elif self._service:
                                self._service.finish_rss_subscribe(rssid=rid, media=media_info)
                        else:
                            self._movie_repo.update_state(
                                title=None, year=None, rssid=rid, state=SubscribeState.RUNNING.value
                            )
                    except (
                        MediaError,
                        DownloadError,
                        IndexerError,
                        RepositoryError,
                        ServiceError,
                        NetworkError,
                    ):
                        self._movie_repo.update_state(
                            title=None, year=None, rssid=rid, state=SubscribeState.RUNNING.value
                        )
                        log.error(
                            f"[Subscribe]{MediaType.MOVIE.display_name} {name_val}"
                            f" 订阅搜索失败：{traceback.format_exc()}"
                        )
            except Exception:
                log.error(
                    f"[Subscribe]{MediaType.MOVIE.display_name} {name_val} 订阅处理失败：{traceback.format_exc()}"
                )
                if rid:
                    try:
                        self._movie_repo.update_state(
                            title=None, year=None, rssid=rid, state=SubscribeState.ERROR.value
                        )
                    except Exception as update_err:
                        log.debug(f"[Subscribe]设置 ERROR 状态失败 rssid={rid}: {update_err}")

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(_process_one, list(rss_movies.values())))

    def _search_tvs(self, state: str = SubscribeState.PENDING.value, rssid: int | None = None) -> None:
        if rssid:
            rss_tvs = self._service.get_subscribe_tvs(rid=rssid) if self._service else {}
        else:
            rss_tvs = self._service.get_subscribe_tvs(state=state) if self._service else {}
        if not rss_tvs:
            return
        log.info(f"[Subscribe]共有 {len(rss_tvs)} 个{MediaType.TV.display_name}订阅需要检索")

        def _process_one(rss_info: dict) -> None:
            if rss_info.get("fuzzy_match"):
                return
            rid = rss_info.get("id")
            name_val = rss_info.get("name")
            year_val = rss_info.get("year") or ""
            tmdbid = rss_info.get("tmdbid")
            over_edition = rss_info.get("over_edition")
            keyword = rss_info.get("keyword")

            try:
                media_info = self._get_media_info(tmdbid, name_val, year_val, MediaType.TV)
                if not media_info or not media_info.tmdb_info:
                    log.warn(f"[Subscribe]{MediaType.TV.display_name} {name_val} TMDB 识别失败，标记为错误状态")
                    self._tv_repo.update_state(
                        title=None, year=None, season=None, rssid=rid, state=SubscribeState.ERROR.value
                    )
                    return

                media_info.set_download_info(
                    download_setting=rss_info.get("download_setting"), save_path=rss_info.get("save_path")
                )
                season = 1
                if rss_info.get("season"):
                    season = int(str(rss_info.get("season")).replace("S", ""))
                media_info.begin_season = season
                media_info.rssid = rid
                total_ep = rss_info.get("total")
                current_ep = rss_info.get("current_ep")

                # 懒更新：TMDB 集数增加时自动同步（优先季详情集数，episode_count 常滞后）
                if rid:
                    try:
                        new_total = 0
                        try:
                            season_detail = self._media_service.get_tmdb_tv_season_detail(media_info.tmdb_id, season)
                            season_eps = season_detail.get("episodes") if isinstance(season_detail, dict) else None
                            if isinstance(season_eps, list):
                                new_total = len(season_eps)
                        except Exception:  # noqa: BLE001
                            new_total = 0
                        if new_total <= 0 and media_info.tmdb_info:
                            new_total = int(
                                self._media_service.get_tmdb_season_episodes_num(
                                    tv_info=media_info.tmdb_info, season=season
                                )
                                or 0
                            )
                        if new_total > 0 and (total_ep is None or new_total > total_ep):
                            log.info(f"[Subscribe]{name_val} S{season} TMDB 总集数更新: {total_ep or 0} -> {new_total}")
                            old_total = int(total_ep or 0)
                            total_ep = int(new_total)
                            new_missing = list(range(old_total + 1, int(new_total) + 1))
                            self._tv_repo.update_total(rssid=rid, total_ep=int(new_total), lack_episodes=new_missing)
                    except Exception as e:  # noqa: BLE001
                        log.debug(f"[Subscribe]{name_val} TMDB 集数检查异常: {e}")
                media_info.keyword = keyword

                episodes = self._tv_episode_repo.get(rid) if rid is not None else None
                if episodes is None:
                    episodes_list = []
                    if current_ep and total_ep is not None:
                        episodes_list = list(range(current_ep, total_ep + 1))
                    elif total_ep is not None and total_ep > 0:
                        tep: int = total_ep
                        episodes_list = list(range(1, tep + 1))
                else:
                    episodes_list = episodes

                rss_no_exists_local = {
                    media_info.tmdb_id: [{"season": season, "episodes": episodes_list, "total_episodes": total_ep}]
                }

                if self._coordinator and not self._coordinator.try_acquire(media_info):
                    log.info(f"[Subscribe]{MediaType.TV.display_name} {name_val} 已被其他策略处理，跳过")
                    self._tv_repo.update_state(
                        title=None, year=None, season=None, rssid=rid, state=SubscribeState.RUNNING.value
                    )
                    return

                with self._lock_context(media_info):
                    if not over_edition:
                        exist_flag, library_no_exists, _ = self._downloader.check_exists_medias(
                            meta_info=media_info, total_ep={season: total_ep}
                        )
                        if exist_flag:
                            if not library_no_exists or not library_no_exists.get(media_info.tmdb_id):
                                log.info(
                                    f"[Subscribe]{MediaType.TV.display_name}"
                                    f" {media_info.get_title_string()} 订阅剧集已全部存在"
                                )
                                if self._service:
                                    self._service.finish_rss_subscribe(rssid=rss_info.get("id"), media=media_info)
                            return
                        rss_no_exists_local = Torrent.get_intersection_episodes(
                            target=rss_no_exists_local, source=library_no_exists, title=media_info.tmdb_id
                        )
                        if rss_no_exists_local.get(media_info.tmdb_id):
                            missing = rss_no_exists_local.get(media_info.tmdb_id)
                            log.info(f"[Subscribe]{media_info.get_title_string()} 订阅缺失季集：{missing}")
                            if self._service:
                                self._service.update_subscribe_tv_lack(
                                    rssid=rid, media_info=media_info, seasoninfo=missing
                                )
                    else:
                        media_info.over_edition = over_edition
                        if rid is not None:
                            media_info.res_order = self._tv_repo.get_filter_order(rssid=rid)

                    self._tv_repo.update_state(
                        title=None, year=None, season=None, rssid=rid, state=SubscribeState.SEARCHING.value
                    )
                    # 搜索站点：订阅未配置时回退到默认订阅设置的 search_sites（与手动搜索一致）。
                    # 不能直接用 rss_info.get("search_sites")，否则空列表会覆盖 effective sites → 0 站点搜索
                    sites = self._get_effective_search_sites(rss_info, MediaType.TV)
                    filters_tv = {
                        "restype": rss_info.get("filter_restype"),
                        "pix": rss_info.get("filter_pix"),
                        "team": rss_info.get("filter_team"),
                        "rule": rss_info.get("filter_rule"),
                        "include": rss_info.get("filter_include"),
                        "exclude": rss_info.get("filter_exclude"),
                        "free": rss_info.get("filter_free"),
                        "site": sites,
                    }
                    search_result, no_exists, _, _ = self._searcher.search_one_media(
                        media_info=media_info,
                        in_from=SearchType.SUBSCRIBE,
                        no_exists=rss_no_exists_local,
                        sites=sites,
                        filters=filters_tv,
                    )
                    if over_edition:
                        if search_result:
                            if self._service:
                                self._service.update_subscribe_over_edition(
                                    rtype=media_info.type, rssid=rid, media=search_result
                                )
                        else:
                            self._tv_repo.update_state(
                                title=None, year=None, season=None, rssid=rid, state=SubscribeState.RUNNING.value
                            )
                    elif not no_exists or not no_exists.get(media_info.tmdb_id):
                        if self._service:
                            self._service.finish_rss_subscribe(rssid=rid, media=media_info)
                    elif search_result:
                        exist_flag, library_no_exists, _ = self._downloader.check_exists_medias(
                            meta_info=media_info, total_ep={season: total_ep}
                        )
                        if not library_no_exists or not library_no_exists.get(media_info.tmdb_id):
                            if self._service:
                                self._service.finish_rss_subscribe(rssid=rid, media=media_info)
                        elif self._service:
                            self._service.update_subscribe_tv_lack(
                                rssid=rid, media_info=media_info, seasoninfo=library_no_exists.get(media_info.tmdb_id)
                            )
                    elif no_exists and self._service:
                        self._service.update_subscribe_tv_lack(
                            rssid=rid, media_info=media_info, seasoninfo=no_exists.get(media_info.tmdb_id)
                        )
            except (MediaError, DownloadError, IndexerError, RepositoryError, ServiceError, NetworkError):
                log.error(f"[Subscribe]{MediaType.TV.display_name} {name_val} 订阅搜索失败：{traceback.format_exc()}")
                self._tv_repo.update_state(
                    title=None, year=None, season=None, rssid=rid, state=SubscribeState.RUNNING.value
                )
            except Exception:
                log.error(f"[Subscribe]{MediaType.TV.display_name} {name_val} 订阅处理失败：{traceback.format_exc()}")
                self._tv_repo.update_state(
                    title=None, year=None, season=None, rssid=rid, state=SubscribeState.ERROR.value
                )

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(_process_one, list(rss_tvs.values())))

    def _get_media_info(self, tmdbid, name, year, mtype, cache=True):
        """综合返回媒体信息；对空 tmdbid 的 name/year/mtype 组合做进程内缓存."""
        key = f"ident:{mtype}:{name or ''}:{year or ''}:{tmdbid or ''}"
        cached = self._ident_cache.get(key)
        if cached is not None:
            return cached

        if tmdbid and not str(tmdbid).startswith("DB:"):
            media_info = meta_info(title=("%s %s" % (name, year)).strip())
            tmdb_info = self._media_cache.get_tmdb_info(mtype=mtype, tmdbid=tmdbid)
            media_info.set_tmdb_info(tmdb_info)
            # en_name 为空或非拉丁时补全英文名，避免日语原名导致英文标题匹配失败
            if self._media_service:
                self._media_service.enrich_en_name(media_info)
            if not (hasattr(media_info, "get_poster_image") and media_info.get_poster_image()):
                log.debug(f"[BaseSearchStrategy] 缓存缺少海报，重新识别: {name} ({year})")
                identified = self._media_service.identify(title=f"{name} {year}".strip(), mtype=mtype)
                if identified and hasattr(identified, "get_poster_image") and identified.get_poster_image():
                    media_info = identified
        else:
            media_info = self._media_service.identify(title=f"{name} {year}".strip(), mtype=mtype)

        if media_info is not None:
            self._ident_cache.set(key, media_info)
        return media_info
