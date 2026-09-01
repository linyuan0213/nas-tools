import os
from typing import BinaryIO

import log
from app.core.exceptions import (
    DomainError,
    RepositoryError,
    ResourceNotFoundError,
    ServiceError,
    ValidationError,
)
from app.db.repositories.category_repo_adapter import CategoryConfigRepositoryAdapter
from app.domain.enums import OsType
from app.domain.mediatypes import MediaType
from app.events import Event
from app.events.constants import SUBTITLE_DOWNLOAD
from app.events.payloads import SubtitleDownloadPayload
from app.storage import LocalStorageBackend, StorageBackendFactory
from app.storage.backends.base import FileInfo, StorageBackend, StorageType
from app.storage.config_models import LocalStorageConfig
from app.utils import SystemUtils


class MediaFileService:
    """
    媒体文件操作业务服务
    """

    def __init__(
        self,
        event_bus,
        storage_backend_repo,
        media_service,
        thread_executor,
        scraper,
    ):
        self._event_bus = event_bus
        self._storage_backend_repo = storage_backend_repo
        self._media_service = media_service
        self._thread_executor = thread_executor
        self._scraper = scraper

    def _resolve_backend(self, backend_id: str) -> StorageBackend:
        """按 backend_id 解析存储后端，空或 local 返回本地后端"""
        if not backend_id or backend_id == "local":
            return LocalStorageBackend(LocalStorageConfig(id="local", name="本地", type=StorageType.LOCAL))
        entity = self._storage_backend_repo.get_by_id(int(backend_id))
        if not entity:
            raise ResourceNotFoundError(f"未找到存储后端: {backend_id}")
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

    @staticmethod
    def _validate_file_name(name: str) -> None:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValidationError(f"非法文件名: {name!r}")

    def get_dir_list(self, in_dir: str, backend_id: str = "") -> list:
        """获取目录列表，支持本地和远程存储后端，失败时抛出异常"""
        result = []
        if backend_id and backend_id != "local":
            backend = self._resolve_backend(backend_id)
            for fi in backend.list_dir(in_dir or "/"):
                item = {
                    "name": os.path.basename(fi.path),
                    "path": fi.path,
                    "is_dir": fi.is_dir,
                }
                if fi.mtime:
                    item["mtime"] = fi.mtime
                if fi.size is not None and not fi.is_dir:
                    item["size"] = fi.size
                    item["ext"] = os.path.splitext(fi.path)[1][1:]
                result.append(item)
            return result

        if not in_dir or in_dir == "/":
            if SystemUtils.get_system() == OsType.WINDOWS:
                partitions = SystemUtils.get_windows_drives()
                if partitions:
                    for p in partitions:
                        result.append({"name": p, "path": p, "is_dir": True})
                else:
                    for f in os.listdir("C:/"):
                        ff = os.path.join("C:/", f)
                        result.append({"name": f, "path": ff.replace("\\", "/"), "is_dir": os.path.isdir(ff)})
            else:
                for f in os.listdir("/"):
                    ff = os.path.join("/", f)
                    result.append({"name": f, "path": ff.replace("\\", "/"), "is_dir": os.path.isdir(ff)})
        else:
            d = os.path.normpath(in_dir)
            if not os.path.isdir(d):
                d = os.path.dirname(d)
            for f in os.listdir(d):
                ff = os.path.join(d, f)
                is_dir = os.path.isdir(ff)
                item = {"name": f, "path": ff.replace("\\", "/"), "is_dir": is_dir}
                try:
                    st = os.stat(ff)
                    item["mtime"] = st.st_mtime
                    item["ctime"] = st.st_ctime
                except OSError:
                    item["mtime"] = None
                    item["ctime"] = None
                if not is_dir:
                    item["ext"] = os.path.splitext(f)[1][1:]
                    try:
                        item["size"] = os.path.getsize(ff)
                    except OSError:
                        item["size"] = None
                result.append(item)
        return result

    def get_library_paths(self, media: dict, sync_svc, downloader_svc=None) -> dict:
        """获取媒体库目录 + 同步源目录 + 同步目标目录"""

        def _make_path(path: str, label: str, ptype: str, backend_id: str = "local"):
            if not path:
                return None
            norm = path.replace("\\", "/").rstrip("/")
            name = os.path.basename(norm) or label
            return {"name": name, "path": norm, "type": ptype, "backend_id": backend_id or "local"}

        def _dedupe(paths: list, seen: set) -> list:
            result = []
            for item in paths:
                if not item:
                    continue
                norm = item["path"]
                if norm in seen:
                    continue
                seen.add(norm)
                result.append(item)
            return result

        library_paths = []
        seen_lib = set()
        movie_paths = media.get("movie_path") or []
        if not isinstance(movie_paths, list):
            movie_paths = [movie_paths] if movie_paths else []
        tv_paths = media.get("tv_path") or []
        if not isinstance(tv_paths, list):
            tv_paths = [tv_paths] if tv_paths else []
        anime_paths = media.get("anime_path") or []
        if not isinstance(anime_paths, list):
            anime_paths = [anime_paths] if anime_paths else []

        movie_backend = media.get("movie_backend") or []
        tv_backend = media.get("tv_backend") or []
        anime_backend = media.get("anime_backend") or []

        for i, p in enumerate(movie_paths):
            item = _make_path(
                p, MediaType.MOVIE.display_name, "movie", movie_backend[i] if i < len(movie_backend) else "local"
            )
            if item:
                library_paths.append(item)
        for i, p in enumerate(tv_paths):
            item = _make_path(p, MediaType.TV.display_name, "tv", tv_backend[i] if i < len(tv_backend) else "local")
            if item:
                library_paths.append(item)
        for i, p in enumerate(anime_paths):
            item = _make_path(
                p, MediaType.ANIME.display_name, "anime", anime_backend[i] if i < len(anime_backend) else "local"
            )
            if item:
                library_paths.append(item)
        library_paths = _dedupe(library_paths, seen_lib)

        sync_source_paths = []
        sync_dest_paths = []
        seen_src = set()
        seen_dst = set()
        try:
            sync_confs = sync_svc.get_sync_paths()
            if isinstance(sync_confs, dict):
                for sp in sync_confs.values():
                    if hasattr(sp, "source"):
                        src = sp.source
                        dest = getattr(sp, "dest", "")
                        src_backend = getattr(sp, "src_backend_id", "local")
                        dst_backend = getattr(sp, "dst_backend_id", "local")
                    elif isinstance(sp, dict):
                        src = sp.get("from") or sp.get("source")
                        dest = sp.get("dest") or sp.get("target") or ""
                        src_backend = sp.get("src_backend_id", "local")
                        dst_backend = sp.get("dst_backend_id", "local")
                    else:
                        src = None
                        dest = ""
                        src_backend = "local"
                        dst_backend = "local"
                    src_item = _make_path(src or "", "同步源目录", "sync", src_backend)
                    if src_item:
                        sync_source_paths.append(src_item)
                    if dest and dest != src:
                        dst_item = _make_path(dest, "同步目标目录", "sync_dest", dst_backend)
                        if dst_item:
                            sync_dest_paths.append(dst_item)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:  # noqa: BLE001
            log.debug(f"[FileOps]忽略异常: {e}")
        sync_source_paths = _dedupe(sync_source_paths, seen_src)
        sync_dest_paths = _dedupe(sync_dest_paths, seen_dst)

        default_path = media.get("media_default_path")
        if not default_path:
            if library_paths:
                default_path = library_paths[0]["path"]
            elif sync_dest_paths:
                default_path = sync_dest_paths[0]["path"]
            elif sync_source_paths:
                default_path = sync_source_paths[0]["path"]
            else:
                default_path = os.path.expanduser("~").replace("\\", "/")

        return {
            "library_paths": library_paths,
            "sync_source_paths": sync_source_paths,
            "sync_dest_paths": sync_dest_paths,
            "default_path": default_path,
        }

    def download_subtitle(self, path: str, name: str) -> None:
        """下载字幕，失败时抛出异常"""
        media = self._media_service.get_media_info(title=name)
        if not media or not media.tmdb_info:
            raise ResourceNotFoundError(f"{name} 无法从TMDB查询到媒体信息")
        if not media.imdb_id:
            media.set_tmdb_info(self._media_service.get_tmdb_info(mtype=media.type, tmdbid=media.tmdb_id))
        self._event_bus.publish(
            Event(
                event_type=SUBTITLE_DOWNLOAD,
                payload=SubtitleDownloadPayload(
                    media_info=media.to_dict(),
                    file=os.path.splitext(path)[0],
                    file_ext=os.path.splitext(name)[-1],
                    bluray=False,
                ),
            )
        )

    def scrap_media_path(self, path: str, backend_id: str = "local") -> str:
        """刮削媒体路径，支持本地和远程后端"""
        if not path:
            return "请指定刮削路径"
        dst_backend = None
        if backend_id and backend_id != "local":
            dst_backend = self._resolve_backend(backend_id)
        self._thread_executor.submit(self._scraper.folder_scraper, path, None, "force_all", dst_backend)
        return "刮削任务已提交，正在后台运行。"

    def make_dir(self, parent: str, name: str, backend_id: str = "local") -> str:
        """在 parent 下创建目录，返回新目录路径"""
        self._validate_file_name(name)
        backend = self._resolve_backend(backend_id)
        target = os.path.join(parent or "/", name).replace("\\", "/")
        if backend.exists(target):
            raise ValidationError(f"目录已存在: {name}")
        backend.mkdir(target, parents=True)
        return target

    def move_or_copy_files(self, files: list[str], dest_dir: str, backend_id: str = "local", move: bool = True) -> str:
        """批量移动/复制文件到目标目录（同后端），部分失败时抛 ServiceError"""
        if not files:
            raise ValidationError("未指定文件")
        if not dest_dir:
            raise ValidationError("未指定目标目录")
        backend = self._resolve_backend(backend_id)
        dest = dest_dir.rstrip("/")
        info = backend.stat(dest)
        if not info or not info.is_dir:
            raise ResourceNotFoundError(f"目标目录不存在: {dest_dir}")
        action = "移动" if move else "复制"
        errors = []
        for f in files:
            try:
                target = os.path.join(dest, os.path.basename(f)).replace("\\", "/")
                if move:
                    backend.move(f, target)
                else:
                    backend.copy(f, target)
            except Exception as e:  # noqa: BLE001
                log.error(f"[FileOps]{action}失败: {f} - {e}")
                errors.append(os.path.basename(f))
        if errors:
            raise ServiceError(f"以下文件{action}失败: {', '.join(errors)}")
        return f"{action}成功"

    def open_download(self, path: str, backend_id: str = "local") -> tuple[BinaryIO, FileInfo]:
        """打开文件下载流，调用方负责 close"""
        if not path:
            raise ValidationError("未指定文件")
        backend = self._resolve_backend(backend_id)
        info = backend.stat(path)
        if not info or info.is_dir:
            raise ResourceNotFoundError(f"文件不存在: {path}")
        return backend.read_stream(path), info

    def save_upload(self, dest_dir: str, name: str, stream: BinaryIO, backend_id: str = "local") -> str:
        """保存上传文件到目标目录，返回文件路径"""
        self._validate_file_name(name)
        if not dest_dir:
            raise ValidationError("未指定目标目录")
        backend = self._resolve_backend(backend_id)
        info = backend.stat(dest_dir)
        if not info or not info.is_dir:
            raise ResourceNotFoundError(f"目标目录不存在: {dest_dir}")
        target = os.path.join(dest_dir, name).replace("\\", "/")
        backend.write_stream(target, stream)
        return target

    def get_category_config(self) -> list[dict]:
        """获取二级分类配置（数据库）"""
        repo = CategoryConfigRepositoryAdapter()
        return [ent.to_dict() for ent in repo.get_all()]

    def update_category_config(self, items: list[dict]) -> str:
        """保存二级分类配置（数据库）"""
        repo = CategoryConfigRepositoryAdapter()
        repo.clear_all()
        for item in items:
            repo.save(
                media_type=item.get("media_type", ""),
                name=item.get("name", ""),
                sort_order=item.get("sort_order", 0),
                is_default=int(item.get("is_default", 0)),
                rules=item.get("rules", {}),
            )
        return "保存成功"
