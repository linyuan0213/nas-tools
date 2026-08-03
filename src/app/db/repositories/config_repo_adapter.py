"""
配置领域 Repository 适配器
将旧版 ConfigRepository 适配为新领域接口
"""

from typing import Any

from app.db.models import (
    CONFIGFILTERGROUP,
    CONFIGFILTERRULES,
    CONFIGMEDIA,
    CONFIGRSSPARSER,
    CONFIGUSERRSS,
    DOWNLOADER,
    MEDIASERVER,
    MESSAGECLIENT,
    TORRENTREMOVETASK,
    USERRSSTASKHISTORY,
)
from app.db.repositories.config_repository import ConfigRepository
from app.domain.entities.config import (
    DownloaderEntity,
    FilterGroupEntity,
    FilterRuleEntity,
    MediaServerEntity,
    MessageClientEntity,
    TorrentRemoveTaskEntity,
)
from app.domain.interfaces.config_repo import (
    IDownloaderRepository,
    IFilterGroupRepository,
    IFilterRuleRepository,
    IMediaServerRepository,
    IMessageClientRepository,
    ITorrentRemoveTaskRepository,
)
from app.utils.json_utils import JsonUtils


class MessageClientRepositoryAdapter(IMessageClientRepository):
    """消息客户端仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_all(self) -> list[MessageClientEntity]:
        rows = self._repo.get_message_client()
        if not rows:
            return []
        return [entity for entity in [MessageClientEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_id(self, cid: int) -> MessageClientEntity | None:
        rows = self._repo.get_message_client(cid)
        if not rows:
            return None
        return MessageClientEntity.from_orm(rows[0])

    def insert(
        self,
        name: str,
        ctype: str,
        config: str,
        switches: list,
        interactive: int,
        enabled: int,
        note: str = "",
        templates: str | None = None,
    ) -> None:
        self._repo.insert_message_client(name, ctype, config, switches, interactive, enabled, note, templates)

    def delete(self, cid: int) -> None:
        self._repo.delete_message_client(cid)

    # 兼容旧 ConfigRepository 方法
    def get_message_client(self, cid: int | None = None) -> list[MESSAGECLIENT]:
        return self._repo.get_message_client(cid)

    def delete_message_client(self, cid: int | None) -> int:
        return self._repo.delete_message_client(cid)

    def update_message_client(self, cid: int, **kwargs) -> int:
        return self._repo.update_message_client(cid=cid, **kwargs)

    def insert_message_client(
        self,
        name: str,
        ctype: str,
        config: str,
        switches: list,
        interactive: int,
        enabled: int,
        note: str = "",
        templates: str | None = None,
    ) -> int:
        return self._repo.insert_message_client(name, ctype, config, switches, interactive, enabled, note, templates)

    def check_message_client(
        self,
        cid: int | None = None,
        interactive: int | None = None,
        enabled: int | None = None,
        ctype: str | None = None,
    ) -> None:
        self._repo.check_message_client(cid, interactive, enabled, ctype)


class DownloaderRepositoryAdapter(IDownloaderRepository):
    """下载器仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_all(self) -> list[DownloaderEntity]:
        rows = self._repo.get_downloaders()
        if not rows:
            return []
        return [entity for entity in [DownloaderEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_id(self, did: int) -> DownloaderEntity | None:
        rows = self._repo.get_downloaders()
        if not rows:
            return None
        for row in rows:
            if int(did) == row.ID:
                return DownloaderEntity.from_orm(row)
        return None

    def insert(
        self, name: str, dtype: str, config: str, transfer: int, only_nexus_media: int, match_path: int, enabled: int
    ) -> None:
        self._repo.update_downloader(
            did=None,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nexus_media=only_nexus_media,
            match_path=match_path,
            rmt_mode="",
            config=config,
            download_dir="",
        )

    def update(
        self,
        did: int,
        name: str,
        dtype: str,
        config: str,
        transfer: int,
        only_nexus_media: int,
        match_path: int,
        enabled: int,
    ) -> None:
        self._repo.update_downloader(
            did=did,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nexus_media=only_nexus_media,
            match_path=match_path,
            rmt_mode="",
            config=config,
            download_dir="",
        )

    def delete(self, did: int) -> None:
        self._repo.delete_downloader(did)

    # 兼容旧 ConfigRepository 方法
    def get_downloaders(self) -> list[DOWNLOADER]:
        return self._repo.get_downloaders()

    def update_downloader(
        self, did, name, enabled, dtype, transfer, only_nexus_media, match_path, rmt_mode, config, download_dir
    ) -> None:
        self._repo.update_downloader(
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

    def delete_downloader(self, did: int | None) -> None:
        self._repo.delete_downloader(did)

    def check_downloader(
        self,
        did: int | None = None,
        transfer: int | None = None,
        only_nexus_media: int | None = None,
        enabled: int | None = None,
        match_path: int | None = None,
    ) -> None:
        self._repo.check_downloader(did, transfer, only_nexus_media, enabled, match_path)


class FilterGroupRepositoryAdapter(IFilterGroupRepository):
    """过滤规则组仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_all(self) -> list[FilterGroupEntity]:
        rows = self._repo.get_config_filter_group()
        if not rows:
            return []
        return [entity for entity in [FilterGroupEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_id(self, gid: int) -> FilterGroupEntity | None:
        rows = self._repo.get_config_filter_group(gid)
        if not rows:
            return None
        return FilterGroupEntity.from_orm(rows[0])

    def insert(self, name: str, default: int = 0) -> int:
        self._repo.add_filter_group(name, default="Y" if default else "N")
        gid = self._repo.get_filter_groupid_by_name(name)
        return int(gid) if gid else 0

    def delete(self, gid: int) -> None:
        self._repo.delete_filtergroup(gid)

    # 兼容旧 ConfigRepository 方法
    def get_config_filter_group(self, gid: int | None = None) -> list[CONFIGFILTERGROUP]:
        return self._repo.get_config_filter_group(gid)

    def add_filter_group(self, name: str, default: str = "N") -> None:
        self._repo.add_filter_group(name, default)

    def get_filter_groupid_by_name(self, name: str) -> int | str:
        return self._repo.get_filter_groupid_by_name(name)

    def set_default_filtergroup(self, groupid: int) -> None:
        self._repo.set_default_filtergroup(groupid)

    def delete_filtergroup(self, groupid: int) -> None:
        self._repo.delete_filtergroup(groupid)


class FilterRuleRepositoryAdapter(IFilterRuleRepository):
    """过滤规则仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_by_group(self, group_id: int) -> list[FilterRuleEntity]:
        rows = self._repo.get_config_filter_rule(group_id)
        if not rows:
            return []
        return [entity for entity in [FilterRuleEntity.from_orm(r) for r in rows] if entity is not None]

    def insert(self, group_id: int, name: str, include: str, exclude: str, note: str, priority: int = 0) -> None:
        item = {
            "group": group_id,
            "name": name,
            "pri": priority,
            "include": include,
            "exclude": exclude,
            "size": None,
            "free": note,
        }
        self._repo.insert_filter_rule(item)

    def delete_by_group(self, group_id: int) -> None:
        self._repo.delete_filtergroup(group_id)

    # 兼容旧 ConfigRepository 方法
    def get_config_filter_rule(self, groupid: int | None = None) -> list[CONFIGFILTERRULES]:
        return self._repo.get_config_filter_rule(groupid)

    def insert_filter_rule(self, item: dict, ruleid: int | None = None) -> None:
        self._repo.insert_filter_rule(item, ruleid)

    def delete_filterrule(self, ruleid: int) -> None:
        self._repo.delete_filterrule(ruleid)


class MediaServerRepositoryAdapter(IMediaServerRepository):
    """媒体服务器仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_all(self) -> list[MediaServerEntity]:
        rows = self._repo.get_media_servers()
        if not rows:
            return []
        return [entity for entity in [MediaServerEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_id(self, sid: int) -> MediaServerEntity | None:
        rows = self._repo.get_media_servers(sid)
        if not rows:
            return None
        return MediaServerEntity.from_orm(rows[0])

    def insert(self, name: str, ctype: str, config: str, enabled: int) -> None:
        # ConfigRepository 使用 update_media_server 同时处理 insert/update
        self._repo.update_media_server(sid=None, name=name, enabled=enabled, config=config, is_default=0, note=None)

    def delete(self, sid: int) -> None:
        self._repo.delete_media_server(sid)

    # 兼容旧 ConfigRepository 方法
    def get_media_servers(self, sid: int | None = None) -> list[MEDIASERVER]:
        return self._repo.get_media_servers(sid)

    def get_media_server_by_name(self, name: str) -> MEDIASERVER | None:
        return self._repo.get_media_server_by_name(name)

    def update_media_server(
        self, sid: int | None, name: str, enabled: int, config: str, is_default: int = 0, note: str | None = None
    ) -> None:
        self._repo.update_media_server(sid, name, enabled, config, is_default, note)

    def set_default_media_server(self, name: str) -> None:
        self._repo.set_default_media_server(name)

    def get_default_media_server(self) -> MEDIASERVER | None:
        return self._repo.get_default_media_server()


class TorrentRemoveTaskRepositoryAdapter(ITorrentRemoveTaskRepository):
    """自动删种任务仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_all(self) -> list[TorrentRemoveTaskEntity]:
        rows = self._repo.get_torrent_remove_tasks()
        if not rows:
            return []
        return [entity for entity in [TorrentRemoveTaskEntity.from_orm(r) for r in rows] if entity is not None]

    def get_by_id(self, tid: int) -> TorrentRemoveTaskEntity | None:
        rows = self._repo.get_torrent_remove_tasks(tid)
        if not rows:
            return None
        return TorrentRemoveTaskEntity.from_orm(rows[0])

    def insert(self, name: str, downloader: str, config: str, enabled: int = 1) -> None:
        cfg = JsonUtils.loads(config) if isinstance(config, str) else config
        self._repo.insert_torrent_remove_task(
            name=name,
            action=0,
            interval=0,
            enabled=enabled,
            samedata=0,
            only_nexus_media=0,
            downloader=downloader,
            config=cfg,
        )

    def delete(self, tid: int) -> None:
        self._repo.delete_torrent_remove_task(tid)

    # 兼容旧 ConfigRepository 方法
    def get_torrent_remove_tasks(self, tid: int | None = None) -> list[TORRENTREMOVETASK]:
        return self._repo.get_torrent_remove_tasks(tid)

    def delete_torrent_remove_task(self, tid: int | None) -> None:
        self._repo.delete_torrent_remove_task(tid)

    def update_torrent_remove_task(self, tid: int, **kwargs: Any) -> bool:
        return self._repo.update_torrent_remove_task(tid, **kwargs)

    def insert_torrent_remove_task(self, **kwargs: Any) -> None:
        self._repo.insert_torrent_remove_task(**kwargs)


class UserRssConfigRepositoryAdapter:
    """自定义RSS配置仓储适配器——逐个代理所有旧方法"""

    def __init__(self, repo=None):
        self._repo = repo or ConfigRepository()

    def get_userrss_parser(self, pid: int | None = None) -> CONFIGRSSPARSER | None | list[CONFIGRSSPARSER]:
        return self._repo.get_userrss_parser(pid)

    def get_userrss_tasks(self, tid: int | None = None) -> list[CONFIGUSERRSS]:
        return self._repo.get_userrss_tasks(tid)

    def insert_userrss_mediainfos(self, tid: int | None = None, mediainfo: object | None = None) -> None:
        self._repo.insert_userrss_mediainfos(tid, mediainfo)

    def insert_userrss_task_history(self, task_id: int, title: str, downloader: str) -> None:
        self._repo.insert_userrss_task_history(task_id, title, downloader)

    def update_userrss_task_info(self, tid: int | None, count: int) -> None:
        self._repo.update_userrss_task_info(tid, count)

    def delete_userrss_task(self, tid: int | None) -> None:
        self._repo.delete_userrss_task(tid)

    def update_userrss_task(self, item: dict) -> None:
        self._repo.update_userrss_task(item)

    def get_userrss_task_history(self, task_id: int) -> list[USERRSSTASKHISTORY]:
        return self._repo.get_userrss_task_history(task_id)

    def check_userrss_task(self, tid: int | None = None, state: str | None = None) -> None:
        self._repo.check_userrss_task(tid, state)

    def delete_userrss_parser(self, pid: int | None) -> None:
        self._repo.delete_userrss_parser(pid)

    def update_userrss_parser(self, item: dict) -> None:
        self._repo.update_userrss_parser(item)


class MediaConfigRepositoryAdapter:
    """媒体库路径配置仓储适配器"""

    def __init__(self, repo: ConfigRepository | None = None):
        self._repo = repo or ConfigRepository()

    def get_media_config(self) -> CONFIGMEDIA | None:
        return self._repo.get_media_config()

    def add_path(self, path_type: str, path: str, backend: str = "") -> None:
        """添加路径到指定类型"""
        cfg = self._repo.get_media_config()
        col_map = {
            "movie": "MOVIE_PATH",
            "tv": "TV_PATH",
            "anime": "ANIME_PATH",
            "unknown": "UNKNOWN_PATH",
        }
        backend_col_map = {
            "movie": "MOVIE_BACKEND",
            "tv": "TV_BACKEND",
            "anime": "ANIME_BACKEND",
            "unknown": "UNKNOWN_BACKEND",
        }
        if path_type not in col_map:
            raise ValueError(f"Unknown path type: {path_type}")

        col = col_map[path_type]
        backend_col = backend_col_map[path_type]
        current = getattr(cfg, col, "") if cfg else ""
        paths = JsonUtils.loads(current) if current else []
        if not isinstance(paths, list):
            paths = [paths]
        if path not in paths:
            paths.append(path)
            self._repo._update_media_config_col(col, JsonUtils.dumps(paths))
            # 同步添加后端
            backend_current = getattr(cfg, backend_col, "") if cfg else ""
            backends = JsonUtils.loads(backend_current) if backend_current else []
            if not isinstance(backends, list):
                backends = []
            backends.append(backend or "local")
            self._repo._update_media_config_col(backend_col, JsonUtils.dumps(backends))

    def remove_path(self, path_type: str, path: str) -> None:
        """从指定类型移除路径"""
        cfg = self._repo.get_media_config()
        col_map = {
            "movie": "MOVIE_PATH",
            "tv": "TV_PATH",
            "anime": "ANIME_PATH",
            "unknown": "UNKNOWN_PATH",
        }
        backend_col_map = {
            "movie": "MOVIE_BACKEND",
            "tv": "TV_BACKEND",
            "anime": "ANIME_BACKEND",
            "unknown": "UNKNOWN_BACKEND",
        }
        if path_type not in col_map:
            raise ValueError(f"Unknown path type: {path_type}")

        col = col_map[path_type]
        backend_col = backend_col_map[path_type]
        current = getattr(cfg, col, "") if cfg else ""
        paths = JsonUtils.loads(current) if current else []
        if not isinstance(paths, list):
            paths = [paths]
        if path in paths:
            idx = paths.index(path)
            paths.pop(idx)
            self._repo._update_media_config_col(col, JsonUtils.dumps(paths))
            # 同步移除后端
            backend_current = getattr(cfg, backend_col, "") if cfg else ""
            backends = JsonUtils.loads(backend_current) if backend_current else []
            if not isinstance(backends, list):
                backends = []
            if idx < len(backends):
                backends.pop(idx)
            self._repo._update_media_config_col(backend_col, JsonUtils.dumps(backends))

    def update_path(self, path_type: str, old_path: str, new_path: str, backend: str = "") -> None:
        """更新指定类型的路径"""
        cfg = self._repo.get_media_config()
        col_map = {
            "movie": "MOVIE_PATH",
            "tv": "TV_PATH",
            "anime": "ANIME_PATH",
            "unknown": "UNKNOWN_PATH",
        }
        backend_col_map = {
            "movie": "MOVIE_BACKEND",
            "tv": "TV_BACKEND",
            "anime": "ANIME_BACKEND",
            "unknown": "UNKNOWN_BACKEND",
        }
        if path_type not in col_map:
            raise ValueError(f"Unknown path type: {path_type}")

        col = col_map[path_type]
        backend_col = backend_col_map[path_type]
        current = getattr(cfg, col, "") if cfg else ""
        paths = JsonUtils.loads(current) if current else []
        if not isinstance(paths, list):
            paths = [paths]
        if old_path in paths:
            idx = paths.index(old_path)
            paths[idx] = new_path
            self._repo._update_media_config_col(col, JsonUtils.dumps(paths))
            # 同步更新后端
            backend_current = getattr(cfg, backend_col, "") if cfg else ""
            backends = JsonUtils.loads(backend_current) if backend_current else []
            if not isinstance(backends, list):
                backends = []
            while len(backends) < len(paths):
                backends.append("local")
            backends[idx] = backend or "local"
            self._repo._update_media_config_col(backend_col, JsonUtils.dumps(backends))

    def set_media_config(
        self,
        movie_path: str,
        tv_path: str,
        anime_path: str,
        unknown_path: str,
        movie_backend: str = "",
        tv_backend: str = "",
        anime_backend: str = "",
        unknown_backend: str = "",
    ) -> None:
        self._repo.set_media_config(
            movie_path, tv_path, anime_path, unknown_path, movie_backend, tv_backend, anime_backend, unknown_backend
        )
