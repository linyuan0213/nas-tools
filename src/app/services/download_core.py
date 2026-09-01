"""
DownloadCore - 下载核心业务逻辑

职责：
- 单个资源下载（download）
- 批量下载（batch_download）
- 媒体库存在性检查（check_exists_medias）
- 种子文件解析（get_torrent_episodes）
- 历史记录查询

依赖注入：所有外部依赖通过构造函数传入。
"""

import os
from typing import Any

import log
from app.core.constants import PT_TAG, RMT_MEDIAEXT
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.system_config import SystemConfig
from app.db.repositories.config_repo_adapter import DownloaderRepositoryAdapter
from app.db.repositories.download_repo_adapter import (
    DownloadHistoryRepositoryAdapter,
    DownloadSettingRepositoryAdapter,
)
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.downloader.client_factory import DownloadClientFactory
from app.downloader.pipeline import DownloadPipeline
from app.downloader.strategy import RemoveStrategy
from app.events.bus import EventBus
from app.events.registry import EventHandlerRegistry  # noqa: F401
from app.media import meta_info
from app.mediaserver import MediaServer
from app.message import Message
from app.schemas.download import Torrent as TorrentInfo
from app.services.download_strategies import EpisodeStrategy, MovieDownloadStrategy, SeasonPackStrategy
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.sites import SiteConf, SiteSubtitle
from app.sites.engine import SiteEngine
from app.sites.site_cache import SiteCache
from app.sites.torrent import Torrent
from app.utils import ExceptionUtils


class DownloadCore:
    """
    下载核心业务服务
    """

    def __init__(
        self,
        client_factory: DownloadClientFactory,
        message: Message,
        mediaserver: MediaServer,
        filetransfer: FileTransfer,
        sites: SiteCache,
        siteconf: SiteConf,
        sitesubtitle: SiteSubtitle,
        event_bus: EventBus,
        download_repo: DownloadHistoryRepositoryAdapter,
        download_setting_repo: DownloadSettingRepositoryAdapter,
        systemconfig: SystemConfig,
        downloader_repo: DownloaderRepositoryAdapter,
        site_engine: SiteEngine,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
    ):
        self._client_factory = client_factory
        self._message = message
        self._mediaserver = mediaserver
        self._filetransfer = filetransfer
        self._sites = sites
        self._siteconf = siteconf
        self._sitesubtitle = sitesubtitle
        self._event_bus = event_bus
        self._download_repo = download_repo
        self._download_setting_repo = download_setting_repo
        self._systemconfig = systemconfig
        self._downloader_repo = downloader_repo
        self._site_engine = site_engine
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._pipeline = DownloadPipeline(
            client_factory=self._client_factory,
            message=self._message,
            mediaserver=self._mediaserver,
            filetransfer=self._filetransfer,
            sites=self._sites,
            siteconf=self._siteconf,
            sitesubtitle=self._sitesubtitle,
            event_bus=self._event_bus,
            download_history_repo=self._download_repo,
            site_engine=self._site_engine,
            site_config_repo=self._site_config_repo,
        )

    # ---------- 媒体存在性检查 ----------

    def check_exists_medias(self, meta_info, no_exists=None, total_ep=None):
        """检查媒体是否已存在于媒体库中."""
        if meta_info.type == MediaType.MOVIE:
            exists = self._filetransfer.get_no_exists_medias(meta_info)
            if exists:
                return True, {}, None
            return False, {}, None
        else:
            season = meta_info.get_season_seq()
            if isinstance(total_ep, dict):
                total = total_ep.get(season)
            else:
                total = total_ep
            if not total:
                total = meta_info.total_episodes
            if not total:
                return False, no_exists or {}, None
            no_exists_result = self._filetransfer.get_no_exists_medias(meta_info, season=season, total_num=total)
            if no_exists_result:
                return False, no_exists_result, None
            return True, {}, None

    # ---------- 核心下载方法 ----------

    def download(
        self,
        media_info,
        is_paused=None,
        tag=None,
        download_dir=None,
        download_setting=None,
        downloader_id=None,
        upload_limit=None,
        download_limit=None,
        torrent_file=None,
        in_from=None,
        user_name=None,
        proxy=None,
        file_indices=None,
        file_names=None,
    ):
        """
        添加下载任务，委托给 DownloadPipeline 执行

        :return: 下载器类型, 种子ID，错误信息
        """
        return self._pipeline.execute(
            media_info=media_info,
            is_paused=is_paused,
            tag=tag,
            download_dir=download_dir,
            download_setting=download_setting,
            downloader_id=downloader_id,
            upload_limit=upload_limit,
            download_limit=download_limit,
            torrent_file=torrent_file,
            in_from=in_from,
            user_name=user_name,
            proxy=proxy,
            file_indices=file_indices,
            file_names=file_names,
        )

    def batch_download(
        self, in_from: Any, media_list: list, need_tvs: dict | None = None, user_name: str | None = None
    ) -> tuple[list, list]:
        download_items: list = []
        download_order = self._client_factory.download_order if self._client_factory else None
        download_list = Torrent.get_download_list(media_list, download_order)

        def _download_callback(item, torrent_file=None, is_paused=None):
            downloader_id, download_id, _ = self.download(
                media_info=item,
                torrent_file=torrent_file,
                is_paused=is_paused,
                in_from=in_from,
                user_name=user_name,
            )
            if download_id and item not in download_items:
                download_items.append(item)
            return downloader_id, download_id, ""

        # 1. 下载所有电影
        download_items = MovieDownloadStrategy.download_movies(
            download_list=download_list,
            download_callback=_download_callback,
            get_download_url_callback=self.get_download_url,
        )

        # 2. 电视剧整季匹配
        if need_tvs:
            need_seasons = SeasonPackStrategy.build_need_seasons(need_tvs)
            _, _, need_tvs = SeasonPackStrategy.find_season_packs(
                download_list=download_list,
                need_seasons=need_seasons,
                need_tvs=need_tvs,
                get_download_url_callback=self.get_download_url,
                download_callback=_download_callback,
                get_torrent_episodes_callback=self.get_torrent_episodes,
            )

        # 3. 电视剧单集匹配
        if need_tvs:
            download_items, need_tvs = EpisodeStrategy.download_episodes(
                download_list=download_list,
                need_tvs=need_tvs,
                get_download_url_callback=self.get_download_url,
                download_callback=_download_callback,
                get_torrent_episodes_callback=self.get_torrent_episodes,
                _set_files_status_callback=self.set_files_status,
                _start_torrents_callback=lambda ids, downloader_id: self.start_torrents(
                    downloader_id=downloader_id, ids=ids
                ),
                return_items=download_items,
            )

        # 4. 从整季包中拆包下载
        if need_tvs:
            download_items, need_tvs = EpisodeStrategy.download_from_season_pack(
                download_list=download_list,
                need_tvs=need_tvs,
                get_download_url_callback=self.get_download_url,
                download_callback=_download_callback,
                get_torrent_episodes_callback=self.get_torrent_episodes,
                set_files_status_callback=self.set_files_status,
                start_torrents_callback=lambda ids, downloader_id: self.start_torrents(
                    downloader_id=downloader_id, ids=ids
                ),
                return_items=download_items,
            )

        left_medias = [item for item in media_list if item not in download_items]
        return download_items, left_medias

    # ---------- 历史记录 / 配置 CRUD 代理 ----------

    def get_torrents(self, downloader_id=None, ids=None, tag=None) -> list[TorrentInfo] | None:
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return None
        try:
            torrents, error_flag = _client.get_torrents(tag=tag, ids=ids)
            if error_flag:
                return None
            return torrents
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_remove_torrents(self, downloader_id=None, config=None):
        if not config or not downloader_id:
            return []
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return []
        config["filter_tags"] = []
        if config.get("only_nexus_media"):
            config["filter_tags"] = config["tags"] + [PT_TAG]
        else:
            config["filter_tags"] = config["tags"]
        strategy = RemoveStrategy.from_dict(config)
        torrents = _client.get_remove_torrents(strategy=strategy)
        if torrents:
            torrents.sort(key=lambda x: x.get("name") or "")
        return torrents

    def get_downloading_torrents(self, downloader_id=None, ids=None, tag=None) -> list[TorrentInfo] | None:
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return None
        try:
            return _client.get_downloading_torrents(tag=tag, ids=ids) or []
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_downloading_progress(self, downloader_id=None, ids=None):
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        downloader_conf = self._client_factory.get_downloader_conf(downloader_id)
        only_nexus_media = downloader_conf.get("only_nexus_media") if downloader_conf else None
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return []
        tag = [PT_TAG] if only_nexus_media else None
        try:
            return _client.get_downloading_progress(tag=tag, ids=ids) or []
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []

    def get_completed_torrents(self, downloader_id=None, ids=None, tag=None) -> list[TorrentInfo]:
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return []
        try:
            return _client.get_completed_torrents(ids=ids, tag=tag) or []
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []

    def set_torrents_tag(self, downloader_id=None, ids=None, tags=None):
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return None
        _client.set_torrents_tag(ids=ids, tags=tags)

    def start_torrents(self, downloader_id=None, ids=None):
        if not ids:
            return False
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return False
        return _client.start_torrents(ids)

    def stop_torrents(self, downloader_id=None, ids=None):
        if not ids:
            return False
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return False
        return _client.stop_torrents(ids)

    def delete_torrents(self, downloader_id=None, ids=None, delete_file=False):
        if not ids:
            return False
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return False
        return _client.delete_torrents(delete_file=delete_file, ids=ids)

    def get_files(self, tid, downloader_id=None):
        _client: Any = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return []
        return _client.get_normalized_files(tid)

    def set_files_status(self, tid, need_episodes, downloader_id=None):
        if not downloader_id:
            downloader_id = self._client_factory.default_downloader_id
        _client: Any = self._client_factory.get_client(downloader_id)
        if not _client:
            return []
        torrent_files = self.get_files(tid=tid, downloader_id=downloader_id)
        if not torrent_files:
            return []
        success_episodes = []
        selected_map = {}
        for torrent_file in torrent_files:
            file_id = torrent_file.get("id")
            file_name = torrent_file.get("name")
            mi = meta_info(file_name)
            if not mi.get_episode_list():
                selected = False
            else:
                selected = set(mi.get_episode_list()).issubset(set(need_episodes))
                if selected:
                    success_episodes = list(set(success_episodes).union(set(mi.get_episode_list())))
            selected_map[file_id] = selected
        if success_episodes and selected_map:
            _client.set_file_selection(tid, selected_map)
        return success_episodes

    def recheck_torrents(self, downloader_id=None, ids=None):
        if not ids:
            return False
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return False
        return _client.recheck_torrents(ids)

    def set_speed_limit(self, downloader_id=None, download_limit=None, upload_limit=None):
        if not downloader_id:
            return
        _client = self._client_factory.get_client(downloader_id)
        if not _client:
            return
        try:
            download_limit = int(download_limit) if download_limit else 0
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            download_limit = 0
        try:
            upload_limit = int(upload_limit) if upload_limit else 0
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            upload_limit = 0
        _client.set_speed_limit(download_limit=download_limit, upload_limit=upload_limit)

    def get_torrent_trackers(self, tid, downloader_id=None):
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return []
        return _client.get_torrent_trackers(tid) or []

    def add_torrent_trackers(self, ids, urls, downloader_id=None):
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return
        _client.add_torrent_trackers(ids, urls)

    def edit_torrent_tracker(self, ids, old_url, new_url, downloader_id=None):
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return
        _client.edit_torrent_tracker(ids, old_url, new_url)

    def remove_torrent_trackers(self, ids, urls, downloader_id=None):
        _client = (
            self._client_factory.get_client(downloader_id) if downloader_id else self._client_factory.default_client
        )
        if not _client:
            return
        _client.remove_torrent_trackers(ids, urls)

    # ---------- 种子解析 ----------

    def get_torrent_episodes(self, url, page_url=None):
        if not url:
            log.error("[Downloader]url 链接为空")
            return [], None
        site_info: Any = self._sites.get_sites(siteurl=url) or {}
        torrent = Torrent(site_engine=self._site_engine)
        file_path, _, _, files, retmsg = torrent.get_torrent_info(
            url=url,
            cookie=site_info.get("cookie"),
            api_key=site_info.get("api_key"),
            bearer_token=site_info.get("bearer_token"),
            ua=site_info.get("ua"),
            referer=page_url if site_info.get("referer") else None,
            proxy=site_info.get("proxy") or False,
        )
        if not files:
            log.error(f"[Downloader]读取种子文件集数出错：{retmsg}")
            if file_path:
                Torrent.delete_torrent_file(file_path)
            return [], None
        episodes = []
        for file in files:
            if os.path.splitext(file)[-1] not in RMT_MEDIAEXT:
                continue
            meta = meta_info(file)
            if not meta.begin_episode:
                continue
            episodes = list(set(episodes).union(set(meta.get_episode_list())))
        return episodes, file_path

    # ---------- 历史记录 / 配置 CRUD 代理 ----------

    def get_download_history(self, date=None, hid=None, num=30, page=1):
        return self._download_repo.get_download_history(date=date, hid=hid, num=num, page=page)

    def get_download_history_by_title(self, title):
        return self._download_repo.get_download_history_by_title(title=title) or []

    def get_download_history_by_downloader(self, downloader, download_id):
        return self._download_repo.get_download_history_by_downloader(downloader=downloader, download_id=download_id)

    # ---------- 下载器 CRUD ----------

    def update_downloader(
        self, did, name, enabled, dtype, transfer, only_nexus_media, match_path, rmt_mode, config, download_dir
    ):
        ret = self._downloader_repo.update_downloader(
            did=did,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nexus_media=only_nexus_media,
            match_path=match_path,
            rmt_mode=rmt_mode,
            config=config,
            download_dir=download_dir,
        )
        self._client_factory._refresh()
        return ret

    def delete_downloader(self, did):
        ret = self._downloader_repo.delete_downloader(did=did)
        self._client_factory._refresh()
        return ret

    def check_downloader(self, did=None, transfer=None, only_nexus_media=None, enabled=None, match_path=None):
        ret = self._downloader_repo.check_downloader(
            did=did, transfer=transfer, only_nexus_media=only_nexus_media, enabled=enabled, match_path=match_path
        )
        self._client_factory._refresh()
        return ret

    def delete_download_setting(self, sid):
        ret = self._download_setting_repo.delete_download_setting(sid=sid)
        self._client_factory._refresh()
        return ret

    def update_download_setting(
        self,
        sid,
        name,
        category,
        tags,
        is_paused,
        upload_limit,
        download_limit,
        ratio_limit,
        seeding_time_limit,
        downloader,
    ):
        ret = self._download_setting_repo.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader,
        )
        self._client_factory._refresh()
        return ret

    # ---------- 静态工具 ----------

    def get_download_url(self, page_url):
        site_info: Any = self._sites.get_sites(siteurl=page_url) or {}
        return self._site_engine.resolve_download_url(
            page_url=page_url,
            user_config={
                "cookie": site_info.get("cookie", ""),
                "ua": site_info.get("ua", ""),
                "headers": site_info.get("headers", {}),
                "proxy": site_info.get("proxy"),
                "api_key": site_info.get("api_key", ""),
                "bearer_token": site_info.get("bearer_token", ""),
            },
        )
