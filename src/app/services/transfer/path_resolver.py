"""TransferPathResolver - 文件转移路径解析与格式化."""

import os
import re
import time
from typing import Any

import log
from app.core.constants import DEFAULT_MOVIE_FORMAT, DEFAULT_TV_FORMAT
from app.core.settings import settings
from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.db.repositories.storage_backend_repo_adapter import StorageBackendRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.services.media_config_service import MediaConfigService
from app.services.transfer.name_format import render
from app.storage import StorageBackendFactory
from app.storage.backends.base import StorageConfig, StorageType
from app.storage.backends.local import LocalStorageBackend
from app.storage.config_models import LocalStorageConfig
from app.utils import NumberUtils, PathUtils, StringUtils, SystemUtils


class TransferPathResolver:
    """负责路径解析、格式化字符串生成和目标目录选择."""

    def __init__(
        self,
        movie_path: list | None = None,
        tv_path: list | None = None,
        anime_path: list | None = None,
        unknown_path: list | None = None,
        movie_backend: list | None = None,
        tv_backend: list | None = None,
        anime_backend: list | None = None,
        unknown_backend: list | None = None,
        movie_category_flag=None,
        tv_category_flag=None,
        anime_category_flag=None,
        movie_dir_rmt_format: str = "",
        movie_file_rmt_format: str = "",
        tv_dir_rmt_format: str = "",
        tv_season_rmt_format: str = "",
        tv_file_rmt_format: str = "",
        storage_backend_repo: StorageBackendRepositoryAdapter | None = None,
    ):
        self._movie_path = movie_path or []
        self._tv_path = tv_path or []
        self._anime_path = anime_path or []
        self._unknown_path = unknown_path or []
        self._movie_backend = movie_backend or []
        self._tv_backend = tv_backend or []
        self._anime_backend = anime_backend or []
        self._unknown_backend = unknown_backend or []
        self._movie_category_flag = movie_category_flag
        self._tv_category_flag = tv_category_flag
        self._anime_category_flag = anime_category_flag
        self._movie_dir_rmt_format = movie_dir_rmt_format
        self._movie_file_rmt_format = movie_file_rmt_format
        self._tv_dir_rmt_format = tv_dir_rmt_format
        self._tv_season_rmt_format = tv_season_rmt_format
        self._tv_file_rmt_format = tv_file_rmt_format
        self._backend_cache: dict[str, Any] = {}
        self._storage_backend_repo = storage_backend_repo or StorageBackendRepositoryAdapter()
        self._media_config_service = None
        self._last_refresh = 0.0
        self._refresh_ttl = 60

    @classmethod
    def from_settings(
        cls,
        media_config_service: MediaConfigService,
        storage_backend_repo: StorageBackendRepositoryAdapter | None = None,
    ) -> "TransferPathResolver":
        """从全局配置构造解析器."""
        adapter = CategoryConfigRepositoryAdapter()
        entities = adapter.get_all()
        movie_flag = any(e.media_type == "movie" for e in entities)
        tv_flag = any(e.media_type == "tv" for e in entities)
        anime_flag = any(e.media_type == "anime" for e in entities)
        media_cfg = media_config_service.get_config()
        media = settings.get("media")

        movie_path = media_cfg.get("movie_path") or []
        movie_backend = media_cfg.get("movie_backend") or []
        tv_path = media_cfg.get("tv_path") or []
        tv_backend = media_cfg.get("tv_backend") or []
        anime_path = media_cfg.get("anime_path") or []
        anime_backend = media_cfg.get("anime_backend") or []
        unknown_path = media_cfg.get("unknown_path") or []

        if not anime_path:
            anime_path = tv_path
            anime_backend = tv_backend

        movie_dir_rmt_format = ""
        movie_file_rmt_format = ""
        tv_dir_rmt_format = ""
        tv_season_rmt_format = ""
        tv_file_rmt_format = ""

        if media:
            movie_name_format = media.get("movie_name_format") or DEFAULT_MOVIE_FORMAT
            movie_formats = movie_name_format.rsplit("/", 1)
            if movie_formats:
                movie_dir_rmt_format = movie_formats[0]
                if len(movie_formats) > 1:
                    movie_file_rmt_format = movie_formats[-1]
            tv_name_format = media.get("tv_name_format") or DEFAULT_TV_FORMAT
            tv_formats = tv_name_format.rsplit("/", 2)
            if tv_formats:
                tv_dir_rmt_format = tv_formats[0]
                if len(tv_formats) > 2:
                    tv_season_rmt_format = tv_formats[-2]
                    tv_file_rmt_format = tv_formats[-1]

        result = cls(
            movie_path=movie_path,
            tv_path=tv_path,
            anime_path=anime_path,
            unknown_path=unknown_path,
            movie_backend=movie_backend,
            tv_backend=tv_backend,
            anime_backend=anime_backend,
            unknown_backend=media_cfg.get("unknown_backend") or [],
            movie_category_flag=movie_flag,
            tv_category_flag=tv_flag,
            anime_category_flag=anime_flag,
            movie_dir_rmt_format=movie_dir_rmt_format,
            movie_file_rmt_format=movie_file_rmt_format,
            tv_dir_rmt_format=tv_dir_rmt_format,
            tv_season_rmt_format=tv_season_rmt_format,
            tv_file_rmt_format=tv_file_rmt_format,
            storage_backend_repo=storage_backend_repo or StorageBackendRepositoryAdapter(),
        )
        result._media_config_service = media_config_service
        return result

    def refresh(self) -> None:
        """重新读取媒体库路径配置，使配置变更无需重启即可生效.

        TTL 守卫：60 秒内不重复读库（转移按文件逐个调用 refresh，
        避免批量转移退化为 N+1 次 DB 往返）；配置源读取失败时沿用旧配置。
        """
        if self._media_config_service is None:
            return
        now = time.time()
        if now - self._last_refresh < self._refresh_ttl:
            return
        try:
            fresh = TransferPathResolver.from_settings(
                media_config_service=self._media_config_service,
                storage_backend_repo=self._storage_backend_repo,
            )
        except Exception as e:  # noqa: BLE001
            log.warn(f"[TransferPathResolver]配置刷新失败，沿用旧配置: {e}")
            return
        self._last_refresh = now
        self._movie_path = fresh._movie_path
        self._tv_path = fresh._tv_path
        self._anime_path = fresh._anime_path
        self._unknown_path = fresh._unknown_path
        self._movie_backend = fresh._movie_backend
        self._tv_backend = fresh._tv_backend
        self._anime_backend = fresh._anime_backend
        self._unknown_backend = fresh._unknown_backend
        self._movie_category_flag = fresh._movie_category_flag
        self._tv_category_flag = fresh._tv_category_flag
        self._anime_category_flag = fresh._anime_category_flag
        self._movie_dir_rmt_format = fresh._movie_dir_rmt_format
        self._movie_file_rmt_format = fresh._movie_file_rmt_format
        self._tv_dir_rmt_format = fresh._tv_dir_rmt_format
        self._tv_season_rmt_format = fresh._tv_season_rmt_format
        self._tv_file_rmt_format = fresh._tv_file_rmt_format

    # ---------- 目标路径属性 ----------

    @property
    def movie_path(self) -> list:
        return self._movie_path

    @property
    def tv_path(self) -> list:
        return self._tv_path

    @property
    def anime_path(self) -> list:
        return self._anime_path

    @property
    def unknown_path(self) -> list:
        return self._unknown_path

    @property
    def movie_category_flag(self):
        return self._movie_category_flag

    @property
    def tv_category_flag(self):
        return self._tv_category_flag

    @property
    def anime_category_flag(self):
        return self._anime_category_flag

    # ---------- 路径判断 ----------

    def is_target_dir_path(self, path):
        """判断是否为目的路径下的路径."""
        if not path:
            return False
        for tv_path in self._tv_path:
            if PathUtils.is_path_in_path(tv_path, path):
                return True
        for movie_path in self._movie_path:
            if PathUtils.is_path_in_path(movie_path, path):
                return True
        for anime_path in self._anime_path:
            if PathUtils.is_path_in_path(anime_path, path):
                return True
        return any(PathUtils.is_path_in_path(unknown_path, path) for unknown_path in self._unknown_path)

    def get_best_target_path(self, mtype, in_path=None, size=0, media=None, media_service=None):
        """查询一个最好的目录返回."""
        if not mtype:
            return None
        if mtype == MediaType.MOVIE:
            dest_paths = self._movie_path
            backends = self._movie_backend
        elif mtype == MediaType.TV:
            dest_paths = self._tv_path
            backends = self._tv_backend
        else:
            dest_paths = self._anime_path
            backends = self._anime_backend
        if not dest_paths:
            return None
        if not isinstance(dest_paths, list):
            return dest_paths
        if isinstance(dest_paths, list) and len(dest_paths) == 1:
            return dest_paths[0]
        # 多后端集数更新：剧集已存在于某后端时，优先选择该目录，避免同一剧集分散到多个后端
        if media is not None and mtype in (MediaType.TV, MediaType.ANIME):
            existing = self._find_existing_media_path(dest_paths, backends, media, media_service)
            if existing:
                return existing
        if in_path:
            max_return_path = None
            max_path_len = 0
            for dest_path in dest_paths:
                try:
                    path_len = len(os.path.commonpath([in_path, dest_path]))
                    if path_len > max_path_len:
                        max_path_len = path_len
                        max_return_path = dest_path
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[PathResolver]commonpath 计算失败: {e}")
                    continue
            if max_return_path:
                return max_return_path
        if size:
            for path in dest_paths:
                if SystemUtils.get_free_space(path) > NumberUtils.get_size_gb(size):
                    return path
        return dest_paths[0]

    def _find_existing_media_path(self, dest_paths: list, backends: list, media, media_service) -> str | None:
        """剧集已存在的目标目录（跨多后端）"""
        for idx, dest_path in enumerate(dest_paths):
            try:
                check_path = self.get_dest_path_by_info(dest_path, media, media_service)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[PathResolver]计算目标路径失败: {e}")
                continue
            if not check_path:
                continue
            backend_id = backends[idx] if idx < len(backends) else "local"
            if backend_id == "local":
                if os.path.isdir(check_path):
                    return dest_path
            else:
                backend = self.resolve_backend_by_id(backend_id)
                if backend and backend.exists(check_path):
                    return dest_path
        return None

    def _get_best_unknown_path(self, in_path):
        """查找最合适的 unknown 目录."""
        if not self._unknown_path:
            return None
        for unknown_path in self._unknown_path:
            if os.path.commonpath([in_path, unknown_path]) not in ["/", "\\"]:
                return unknown_path
        return self._unknown_path[0]

    def _get_backend_for_path(self, path: str, path_list: list, backend_list: list) -> str:
        """根据路径查找对应的后端 ID."""
        if not backend_list:
            return "local"
        for idx, p in enumerate(path_list):
            if PathUtils.is_path_in_path(p, path) and idx < len(backend_list):
                return backend_list[idx] or "local"
        return "local"

    def resolve_dst_backend(self, dist_path: str, mtype: MediaType):
        """根据目标路径和媒体类型解析目标存储后端."""
        backend_id = "local"
        if mtype == MediaType.MOVIE:
            backend_id = self._get_backend_for_path(dist_path, self._movie_path, self._movie_backend)
        elif mtype == MediaType.TV:
            backend_id = self._get_backend_for_path(dist_path, self._tv_path, self._tv_backend)
        else:
            backend_id = self._get_backend_for_path(dist_path, self._anime_path, self._anime_backend)
        if backend_id == "local":
            return None
        entity = self._storage_backend_repo.get_by_id(int(backend_id))
        if not entity:
            return None
        info = StorageBackendFactory.get_config_info(entity.type)
        if info:
            stype, cls = info
        else:
            stype, cls = StorageType.LOCAL, LocalStorageConfig
        config = cls(id=str(entity.id), name=entity.name, type=stype, enabled=entity.enabled)
        for k, v in entity.config.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return StorageBackendFactory.create(config)

    def resolve_backend_by_id(self, backend_id: str):
        """根据 ID 解析存储后端（本地返回 LocalStorageBackend 实例，带缓存）."""
        if not backend_id or backend_id == "local":
            return LocalStorageBackend(StorageConfig(id="local", name="local", type=StorageType.LOCAL))
        cached = self._backend_cache.get(backend_id)
        if cached is not None:
            return cached
        entity = self._storage_backend_repo.get_by_id(int(backend_id))
        if not entity:
            return None
        info = StorageBackendFactory.get_config_info(entity.type)
        if info:
            stype, cls = info
        else:
            stype, cls = StorageType.LOCAL, LocalStorageConfig
        config = cls(id=str(entity.id), name=entity.name, type=stype, enabled=entity.enabled)
        for k, v in entity.config.items():
            if hasattr(config, k):
                setattr(config, k, v)
        backend = StorageBackendFactory.create(config)
        self._backend_cache[backend_id] = backend
        return backend

    # ---------- 格式化 ----------

    def get_format_dict(self, media, media_service=None) -> dict:
        """根据媒体信息，返回 Format 字典."""
        if not media:
            return {}
        if media_service is None and re.search(
            r"\{en_title\}|\{episode_title\}",
            "".join(
                (
                    self._movie_dir_rmt_format,
                    self._movie_file_rmt_format,
                    self._tv_dir_rmt_format,
                    self._tv_season_rmt_format,
                    self._tv_file_rmt_format,
                )
            ),
        ):
            log.warn(
                "[TransferPathResolver]重命名格式使用了 {en_title} / {episode_title}，"
                "但未传入 media_service，这两项将渲染为空，请检查 DI 配置"
            )
        episode_title = media_service.get_episode_title(media) if media_service else ""
        en_title = media_service.get_tmdb_en_title(media) if media_service else ""
        media_format_dict = {
            "title": StringUtils.clear_file_name(media.title),
            "en_title": StringUtils.clear_file_name(en_title),
            "original_name": StringUtils.clear_file_name(os.path.splitext(media.org_string or "")[0]),
            "rev_name": StringUtils.clear_file_name(os.path.splitext(media.rev_string or "")[0]),
            "original_title": StringUtils.clear_file_name(media.original_title),
            "name": StringUtils.clear_file_name(media.get_name()),
            "year": media.year,
            "edition": media.get_edtion_string() or None,
            "videoFormat": media.resource_pix,
            "source": media.resource_type,
            "releaseGroup": media.resource_team,
            "customization": media.customization,
            "effect": media.resource_effect,
            "videoCodec": media.video_encode,
            "audioCodec": media.audio_encode,
            "tmdbid": media.tmdb_id,
            "imdbid": media.imdb_id,
            "media_type": media.type.value if media.type else None,
            "category": media.category,
            "season": media.get_season_seq(),
            "episode": media.get_episode_seqs(),
            "episode_title": StringUtils.clear_file_name(episode_title),
            "season_episode": f"{media.get_season_item()}{media.get_episode_items()}",
            "part": media.part,
        }
        for i in media_format_dict:
            if not media_format_dict[i]:
                media_format_dict[i] = "\t"
        return media_format_dict

    def get_movie_dest_path(self, media_info, media_service=None):
        """计算电影文件路径."""
        format_dict = self.get_format_dict(media_info, media_service)
        dir_name = render(self._movie_dir_rmt_format, format_dict)
        file_name = render(self._movie_file_rmt_format, format_dict)
        return dir_name, file_name

    def get_tv_dest_path(self, media_info, media_service=None):
        """计算电视剧文件路径."""
        format_dict = self.get_format_dict(media_info, media_service)
        dir_name = render(self._tv_dir_rmt_format, format_dict)
        season_name = render(self._tv_season_rmt_format, format_dict)
        file_name = render(self._tv_file_rmt_format, format_dict)
        return dir_name, season_name, file_name

    def get_dest_path_by_info(self, dest, meta_info, media_service):
        """拼装转移重命名后的新文件地址."""
        if not dest or not meta_info:
            return None
        if meta_info.type == MediaType.MOVIE:
            dir_name, _ = self.get_movie_dest_path(meta_info, media_service)
            if self._movie_category_flag:
                return os.path.join(dest, meta_info.category, dir_name)
            else:
                return os.path.join(dest, dir_name)
        else:
            dir_name, season_name, _ = self.get_tv_dest_path(meta_info, media_service)
            if meta_info.type == MediaType.TV:
                if self._tv_category_flag:
                    return os.path.join(dest, meta_info.category, dir_name, season_name)
                return os.path.join(dest, dir_name, season_name)
            # 动漫：专用动漫目录时不加分类子目录；回退 TV 目录时按分类进子目录
            is_dedicated_anime = any(PathUtils.is_path_in_path(p, dest) for p in self._anime_path)
            if is_dedicated_anime:
                return os.path.join(dest, dir_name, season_name)
            if self._tv_category_flag:
                return os.path.join(dest, meta_info.category, dir_name, season_name)
            return os.path.join(dest, dir_name, season_name)
