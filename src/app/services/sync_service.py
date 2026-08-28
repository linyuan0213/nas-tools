"""
SyncService - 同步/转移业务层
将 web/controllers/sync.py 中的业务逻辑下沉到可独立测试的 Service。
"""

import importlib
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import Future, wait
from typing import Any
from urllib.parse import unquote

import log
from app.core.constants import RMT_AUDIO_TRACK_EXT, RMT_MEDIAEXT, RMT_SUBEXT
from app.core.exceptions import DomainError, RepositoryError, ServiceError, ValidationError
from app.core.settings import settings
from app.db.repositories.storage_backend_repo_adapter import StorageBackendRepositoryAdapter
from app.domain.entities.sync import SyncPathEntity
from app.domain.entities.transfer import TransferUnknownEntity
from app.domain.enums import SyncType
from app.domain.mediatypes import MediaType
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.infrastructure.thread import ThreadExecutor
from app.media import MediaCache
from app.schemas.sync import (
    ManualTransferResultDTO,
    ReIdentifyResultDTO,
    SimpleResultDTO,
)
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.services.sync_engine import SyncEngine as Sync
from app.services.web import set_config_directory
from app.storage import StorageBackendFactory
from app.storage.backends.base import StorageType
from app.storage.config_models import LocalStorageConfig
from app.utils import EpisodeFormat, ExceptionUtils, StringUtils


class SyncService:
    """
    同步/转移业务服务
    负责：
    - 同步目录的校验与增删改查业务编排
    - 手工转移/自定义识别/重新识别的业务编排
    """

    def __init__(
        self,
        sync: Sync,
        filetransfer: FileTransfer,
        media_cache: MediaCache,
        thread_executor: ThreadExecutor,
        storage_backend_repo: StorageBackendRepositoryAdapter,
    ):
        self._sync = sync
        self._filetransfer = filetransfer
        self._media_cache = media_cache
        self._thread_executor = thread_executor
        self._storage_backend_repo = storage_backend_repo

    # ---------- 同步目录校验 ----------

    def _validate_sync_path(
        self,
        source: str,
        dest: str,
        mode: str,
        src_backend: str = "local",
        dst_backend: str = "local",
    ) -> None:
        """
        校验同步目录参数（不判断存储层是否存在）
        失败时抛出 ValidationError
        """
        source = os.path.normpath(source)
        if dest:
            dest = os.path.normpath(dest)

        entity = SyncPathEntity(
            id=0,
            source=source,
            dest=dest or "",
            unknown="",
            mode=mode,
            compatibility=False,
            rename=False,
            enabled=False,
            note=None,
        )
        errors = entity.validate()
        if errors:
            raise ValidationError(errors[0])

        if dest and SyncPathEntity.is_subpath(source, dest):
            raise ValidationError("目的目录不可包含在源目录中")
        if mode == "link" and dest and src_backend == "local" and dst_backend == "local":
            err = SyncPathEntity.validate_hardlink(source, dest)
            if err:
                raise ValidationError(err)

    def add_or_edit_sync_path(
        self,
        sid: int,
        source: str,
        dest: str,
        unknown: str,
        mode: str,
        operation: str = "",
        src_backend: str = "",
        dst_backend: str = "",
        compatibility: int = 0,
        rename: int = 0,
        enabled: int = 0,
    ) -> None:
        """
        添加或编辑同步目录
        失败时抛出具体异常
        """
        self._validate_sync_path(source, dest, mode, src_backend or "local", dst_backend or "local")

        # windows目录用\，linux目录用/
        source = os.path.normpath(source)
        if dest:
            dest = os.path.normpath(dest)
        if unknown:
            unknown = os.path.normpath(unknown)

        # 编辑先删再增
        if sid:
            self._sync.delete_sync_path(sid)
        # 若启用，则关闭其他相同源目录的同步目录
        if enabled == 1:
            self._sync.check_source(source=source, dest=dest)
        # 插入数据库
        self._sync.insert_sync_path(
            source=source,
            dest=dest,
            unknown=unknown,
            mode=mode,
            operation=operation or mode,
            src_backend=src_backend or "local",
            dst_backend=dst_backend or "local",
            compatibility=bool(compatibility),
            rename=bool(rename),
            enabled=bool(enabled),
        )

    def check_sync_path(self, sid: int, flag: str, checked: bool) -> None:
        """
        切换同步目录配置项
        :param flag: compatibility / rename / enable
        失败时抛出 ValidationError
        """
        if flag == "compatibility":
            self._sync.check_sync_paths(sid=sid, compatibility=checked)
        elif flag == "rename":
            self._sync.check_sync_paths(sid=sid, rename=checked)
        elif flag == "enable":
            if checked:
                self._sync.check_source(sid=str(sid))
            self._sync.check_sync_paths(sid=sid, enabled=checked)
        else:
            raise ValidationError(f"无效的配置项标志: {flag}")

    # ---------- 手工转移 ----------

    def delete_sync_path(self, sid: int) -> SimpleResultDTO:
        """删除同步目录"""
        self._sync.delete_sync_path(sid)
        return SimpleResultDTO(success=True)

    @staticmethod
    def build_media_type(mtype: str) -> MediaType:
        """根据前端类型字符串解析为 MediaType 枚举"""
        return MediaType.from_string(mtype)

    def manual_transfer(
        self,
        inpath: str,
        syncmod,
        outpath: str | None = None,
        media_type: MediaType | None = None,
        episode_format: str | None = None,
        episode_details: str | None = None,
        episode_part: str | None = None,
        episode_offset: str | None = None,
        min_filesize: int | None = None,
        tmdbid: int | None = None,
        season: int | None = None,
        need_fix_all: bool = False,
        src_backend_id: str = "local",
        dst_backend_id: str = "",
    ) -> ManualTransferResultDTO:
        """
        手工转移文件
        验证参数后提交后台线程执行，避免 API 超时
        支持 webdav/openlist 等远程存储源：先暂存到本地临时目录再走本地转移管道
        """
        inpath = os.path.normpath(inpath)
        if outpath:
            outpath = os.path.normpath(outpath)
        # 目标后端（用于判断是否同源后端）
        dst_backend_obj = self._resolve_dst_backend_by_dest(outpath or "", dst_backend_id or None)
        if src_backend_id and src_backend_id != "local":
            src_backend = self._resolve_backend(src_backend_id)
            if not src_backend or not src_backend.exists(inpath):
                return ManualTransferResultDTO(success=False, message="输入路径不存在")
            # 同后端：无需下载暂存，直接走后端服务端复制
            if dst_backend_obj is not None and str(getattr(dst_backend_obj, "id", "")) == str(src_backend_id):
                episode = None
                if episode_format:
                    episode = (
                        EpisodeFormat(episode_format, episode_details or "", episode_part or "", episode_offset or ""),
                        need_fix_all,
                    )
                tmdb_info = None
                if tmdbid:
                    tmdb_info = self._media_cache.get_tmdb_info(mtype=media_type or MediaType.MOVIE, tmdbid=tmdbid)
                    if not tmdb_info:
                        return ManualTransferResultDTO(success=False, message="识别失败，无法查询到TMDB信息")
                self._submit_manual_transfer(
                    inpath,
                    syncmod,
                    outpath,
                    media_type,
                    episode,
                    min_filesize,
                    tmdb_info,
                    season,
                    dst_backend_obj,
                    src_backend=src_backend,
                )
                return ManualTransferResultDTO(success=True, message="转移任务已提交，正在后台执行")
            # 跨后端远程源：暂存到本地临时目录
            staged = self._stage_remote_source(inpath, src_backend_id)
            if not staged:
                return ManualTransferResultDTO(success=False, message="输入路径不存在")
            inpath = staged
        elif not os.path.exists(inpath):
            return ManualTransferResultDTO(success=False, message="输入路径不存在")

        episode = None
        if episode_format:
            episode = (
                EpisodeFormat(episode_format, episode_details or "", episode_part or "", episode_offset or ""),
                need_fix_all,
            )

        tmdb_info = None
        if tmdbid:
            tmdb_info = self._media_cache.get_tmdb_info(mtype=media_type or MediaType.MOVIE, tmdbid=tmdbid)
            if not tmdb_info:
                return ManualTransferResultDTO(success=False, message="识别失败，无法查询到TMDB信息")

        # 根据目的目录查找目标后端
        dst_backend = dst_backend_obj or self._resolve_dst_backend_by_dest(outpath or "")

        return self._submit_manual_transfer(
            inpath, syncmod, outpath, media_type, episode, min_filesize, tmdb_info, season, dst_backend
        )

    def _submit_manual_transfer(
        self,
        inpath: str,
        syncmod,
        outpath: str | None,
        media_type,
        episode,
        min_filesize: int | None,
        tmdb_info,
        season: int | None,
        dst_backend,
        src_backend=None,
    ) -> ManualTransferResultDTO:
        """提交后台线程执行转移，避免 API 超时"""
        self._thread_executor.submit(
            self._filetransfer.transfer_media,
            SyncType.MAN,
            inpath,
            syncmod,
            None,
            outpath,
            None,
            tmdb_info,
            media_type,
            season,
            episode,
            min_filesize,
            True,
            False,
            src_backend,
            dst_backend,
        )

        return ManualTransferResultDTO(success=True, message="转移任务已提交，正在后台执行")

    def _resolve_dst_backend_by_dest(self, dest: str, dst_backend_id: str | None = None):
        """根据目的目录查找对应同步配置的目标后端实例；dst_backend_id 显式指定时优先使用"""
        if dst_backend_id:
            dst_backend_id = str(dst_backend_id)
            if dst_backend_id == "local":
                return None
        else:
            dst_backend_id = self._filetransfer.get_sync_backend_by_dest(dest)
        if dst_backend_id == "local":
            return None
        try:
            entity = self._storage_backend_repo.get_by_id(int(dst_backend_id))
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
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:  # noqa: BLE001
            log.debug(f"[sync_service]忽略异常: {e}")
        return None

    def _resolve_backend(self, backend_id: str):
        """按 id 解析存储后端实例，失败返回 None"""
        try:
            entity = self._storage_backend_repo.get_by_id(int(backend_id))
            if not entity:
                return None
            info = StorageBackendFactory.get_config_info(entity.type)
            stype, cls = info if info else (StorageType.LOCAL, LocalStorageConfig)
            config = cls(id=str(entity.id), name=entity.name, type=stype, enabled=entity.enabled)
            for k, v in entity.config.items():
                if hasattr(config, k):
                    setattr(config, k, v)
            return StorageBackendFactory.create(config)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[sync_service]解析存储后端失败: {e}")
        return None

    def remote_path_exists(self, path: str, backend_id: str) -> bool:
        """远程存储源路径是否存在"""
        backend = self._resolve_backend(backend_id)
        if not backend:
            return False
        try:
            return bool(backend.exists(path))
        except Exception as e:  # noqa: BLE001
            log.debug(f"[sync_service]远程路径检查失败: {e}")
        return False

    def _stage_remote_source(self, remote_path: str, backend_id: str) -> str:
        """递归下载远程源（文件或目录）到本地临时目录，返回本地路径；失败返回空串"""
        backend = self._resolve_backend(backend_id)
        if not backend:
            return ""
        try:
            local_root = tempfile.mkdtemp(prefix="nm_stage_")
            if not backend.exists(remote_path):
                return ""
            info = backend.stat(remote_path)
            local_target = os.path.join(local_root, os.path.basename(remote_path.rstrip("/")) or "source")
            if info and not info.is_dir:
                os.makedirs(os.path.dirname(local_target), exist_ok=True)
                with open(local_target, "wb") as f, backend.read_stream(remote_path) as src:
                    shutil.copyfileobj(src, f)
                return local_target
            self._stage_remote_dir(backend, remote_path, local_target)
            return local_target
        except Exception as e:  # noqa: BLE001
            log.error(f"[sync_service]远程源暂存失败: {e}")
        return ""

    def _stage_remote_dir(self, backend, remote_path: str, local_dir: str) -> None:
        """递归暂存远程目录"""
        os.makedirs(local_dir, exist_ok=True)
        for fi in backend.list_dir(remote_path):
            rel = os.path.basename(fi.path.rstrip("/"))
            local_item = os.path.join(local_dir, rel or "item")
            if fi.is_dir:
                self._stage_remote_dir(backend, fi.path, local_item)
            else:
                os.makedirs(os.path.dirname(local_item), exist_ok=True)
                with open(local_item, "wb") as f, backend.read_stream(fi.path) as src:
                    shutil.copyfileobj(src, f)

    # ---------- 重新识别 ----------

    def re_identify_items(self, flag: str, ids: list) -> ReIdentifyResultDTO:
        """
        批量重新识别（unidentification / history）
        :param flag: "unidentification" 或 "history"
        :param ids: ID 列表
        提交后台线程执行，避免 API 超时；ID 级并发，单个失败不影响其他。
        """
        lock_key = f"sync:re_identify:{flag}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=1800)
        acquired = lock.acquire()
        if not acquired:
            return ReIdentifyResultDTO(success=False, message="重新识别任务正在执行中")

        def _do_one(wid):
            try:
                if flag == "unidentification":
                    unknowninfo = self._filetransfer.get_unknown_info_by_id(wid)
                    if not unknowninfo:
                        return
                    path = unknowninfo.path
                    dest_dir = str(unknowninfo.dest or "")
                    operation = unknowninfo.mode or ""
                elif flag == "history":
                    transinfo = self._filetransfer.get_transfer_info_by_id(wid)
                    if not transinfo:
                        return
                    path = os.path.join(str(transinfo.source_path or ""), str(transinfo.source_filename or ""))
                    dest_dir = str(transinfo.dest or "")
                    operation = transinfo.mode or ""
                else:
                    return

                if not dest_dir:
                    dest_dir = ""
                if not path:
                    return

                dst_backend = self._resolve_dst_backend_by_dest(dest_dir)
                succ_flag, msg = self._filetransfer.transfer_media(
                    in_from=SyncType.MAN,
                    operation=operation,
                    in_path=path,
                    target_dir=dest_dir,
                    dst_backend=dst_backend,
                )
                if succ_flag and flag == "unidentification":
                    self._filetransfer.update_transfer_unknown_state(path)
            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as err:
                ExceptionUtils.exception_traceback(err)

        def _do_re_identify():
            try:
                if self._thread_executor is None:
                    for wid in ids:
                        _do_one(wid)
                else:
                    futures = [self._thread_executor.submit(_do_one, wid) for wid in ids]

                    wait(futures)
            finally:
                lock.release()

        self._thread_executor.submit(_do_re_identify)
        return ReIdentifyResultDTO(success=True, message="重新识别任务已提交，正在后台执行")

    # ---------- 查询 ----------

    def get_sync_paths(self, sid: str | None = None):
        if sid is not None:
            cfg = self._sync.get_sync_path_conf(sid)
            return cfg.to_dict() if cfg else None
        return {k: v.to_dict() for k, v in self._sync.get_all_sync_path_conf().items()}

    def transfer_sync(self, sid: str | None = None):
        """触发指定同步目录的同步转移"""
        return self._sync.transfer_sync(sid=sid)

    def get_transfer_info_by_id(self, logid: int):
        return self._filetransfer.get_transfer_info_by_id(logid)

    def get_unknown_info_by_id(self, tid: int) -> TransferUnknownEntity | None:
        return self._filetransfer.get_unknown_info_by_id(tid)

    def get_sub_path(self, directory: str, ft: str = "ALL") -> list[dict]:
        """
        查询下级子目录/文件（文件大小通过线程池并发获取）
        """
        r = []
        if not directory or directory == "/":
            dirs = [os.path.join("/", f) for f in os.listdir("/")]
        else:
            d = os.path.normpath(unquote(directory))
            if not os.path.isdir(d):
                d = os.path.dirname(d)
            dirs = [os.path.join(d, f) for f in os.listdir(d)]
        dirs.sort()

        def _build_item(ff: str) -> dict | None:
            if os.path.isdir(ff):
                if "ONLYDIR" in ft or "ALL" in ft:
                    return {
                        "path": ff.replace("\\", "/"),
                        "name": os.path.basename(ff),
                        "type": "dir",
                        "rel": os.path.dirname(ff).replace("\\", "/"),
                    }
                return None
            ext = os.path.splitext(ff)[-1][1:]
            ext_lower = f".{str(ext).lower()}"
            flag = (
                "ONLYFILE" in ft
                or "ALL" in ft
                or ("MEDIAFILE" in ft and ext_lower in RMT_MEDIAEXT)
                or ("SUBFILE" in ft and ext_lower in RMT_SUBEXT)
                or ("AUDIOTRACKFILE" in ft and ext_lower in RMT_AUDIO_TRACK_EXT)
            )
            if not flag:
                return None
            return {
                "path": ff.replace("\\", "/"),
                "name": os.path.basename(ff),
                "type": "file",
                "rel": os.path.dirname(ff).replace("\\", "/"),
                "ext": ext,
                "size": StringUtils.str_filesize(os.path.getsize(ff)),
            }

        results = self._run_parallel(dirs, _build_item)
        for item in results:
            if item is not None:
                r.append(item)
        return r

    def _run_parallel(self, items: list, func: Callable[[Any], Any]) -> list[Any]:
        """对无依赖任务使用线程池并发执行；失败隔离，返回结果列表."""
        if not items or self._thread_executor is None:
            return [func(item) for item in items]

        def _wrapper(item):
            try:
                return func(item)
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                return None

        futures: list[Future] = [self._thread_executor.submit(_wrapper, item) for item in items]
        wait(futures)
        return [f.result() for f in futures]

    # ---------- 文件重命名 ----------

    @staticmethod
    def rename_file(path: str, name: str) -> SimpleResultDTO:
        """重命名文件/目录"""
        if not path or not name:
            return SimpleResultDTO(success=True)
        try:
            shutil.move(path, os.path.join(os.path.dirname(path), name))
            return SimpleResultDTO(success=True)
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return SimpleResultDTO(success=False, message=str(e))

    # ---------- 测试命令执行 ----------

    @staticmethod
    def exec_test_command(cmd: str):
        """
        执行安全映射内的测试命令，返回调用结果或 None。

        注意：此为遗留的反射式测试入口，仅保留少量仍可实例化的核心模块，
        新增模块测试请使用专用 Service/Client 的 test_connection 方法。
        """
        m = re.match(r"^(\w+)\(\)\.(\w+)\(\)$", cmd.strip())
        if not m:
            return None
        obj_name, method_name = m.groups()
        safe_mapping = {
            "Config": ("config", "Config"),
            "MessageCenter": ("app.message.message_center", "MessageCenter"),
            "Downloader": ("app.services.downloader_core", "DownloaderCore"),
            "MediaServer": ("app.mediaserver", "MediaServer"),
            "SiteCache": ("app.sites.site_cache", "SiteCache"),
            "RssChecker": ("app.services.rss_automation.task_service", "RssTaskService"),
            "SubscriptionMonitor": ("app.services.subscribe.monitor", "SubscriptionMonitor"),
            "SchedulerCore": ("app.services.scheduler_core", "SchedulerCore"),
            "Scraper": ("app.media", "Scraper"),
        }
        module_path, class_name = safe_mapping.get(obj_name, (None, None))
        if not module_path or not class_name:
            return None
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
            obj = cls()
            if hasattr(obj, method_name):
                return getattr(obj, method_name)()
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:  # noqa: BLE001
            log.debug(f"[sync_service]忽略异常: {e}")
        return None

    @classmethod
    def test_connection(cls, command) -> SimpleResultDTO:
        """
        测试模块连接状态
        """
        ret = None
        module_obj = None
        if not command:
            return SimpleResultDTO(success=True)
        try:
            if isinstance(command, list):
                for cmd_str in command:
                    ret = cls.exec_test_command(cmd_str)
                    if not ret:
                        break
            else:
                if command.find("|") != -1:
                    module = command.split("|")[0]
                    class_name = command.split("|")[1]
                    module_obj = getattr(importlib.import_module(module), class_name)()
                    if hasattr(module_obj, "init_config"):
                        module_obj.init_config()
                    ret = module_obj.get_status()
                else:
                    ret = cls.exec_test_command(command)
            if module_obj:
                if hasattr(module_obj, "init_config"):
                    module_obj.init_config()
        except (ServiceError, RepositoryError, DomainError):
            raise
        except Exception as e:
            ret = None
            ExceptionUtils.exception_traceback(e)
        return SimpleResultDTO(success=bool(ret))

    # ---------- 目录配置更新 ----------

    @staticmethod
    def update_directory(oper: str, key: str, value: str, replace_value: str | None = None) -> SimpleResultDTO:
        """更新配置中的目录路径"""
        cfg = set_config_directory(settings.get(), oper, key, value, replace_value)
        settings.save(cfg)
        return SimpleResultDTO(success=True)
