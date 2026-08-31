"""统一转移管道 — 目录同步与下载器完成转移的统一入口。"""

import os
from typing import Any

import log
from app.core.exceptions import ValidationError
from app.core.settings import settings
from app.db.repositories.storage_backend_repo_adapter import StorageBackendRepositoryAdapter
from app.db.repositories.transfer_repo_adapter import TransferBlacklistRepositoryAdapter
from app.domain.entities.transfer_task import SourceType, TransferTask
from app.domain.enums import SyncType
from app.services.filetransfer_service import FileTransferService
from app.services.scrape_queue_service import ScrapeQueueService
from app.storage.backends.base import StorageBackend, StorageType
from app.storage.config_models import LocalStorageConfig
from app.storage.factory import StorageBackendFactory


class TransferPipeline:
    """
    统一转移管道。

    无论是目录同步（SyncEngine）还是下载器完成（DownloaderCore），
    文件整理都通过本管道执行，确保行为一致：
    1. 文件发现
    2. 媒体识别
    3. 目标路径 + 后端解析
    4. 执行转移
    5. 刮削元数据
    6. 写入黑名单（避免重复处理）
    7. 来源特定后处理（如下载器删种）
    """

    def __init__(
        self,
        filetransfer: FileTransferService,
        scrape_queue_service: ScrapeQueueService,
        blacklist_repo: TransferBlacklistRepositoryAdapter,
        backend_repo: StorageBackendRepositoryAdapter,
    ):
        self._filetransfer = filetransfer
        self._scrape_queue_service = scrape_queue_service
        self._blacklist = blacklist_repo
        self._backend_repo = backend_repo

    def process(self, task: TransferTask) -> tuple[bool, str]:
        """
        执行单个转移任务。

        :return: (success, message)
        """
        try:
            task.validate()
        except ValidationError as e:
            return False, e.message

        # ---------- 1. 解析目标后端 ----------
        dst_backend = self._resolve_backend(task.dst_backend_id)

        # ---------- 2. 逐个文件处理 ----------
        total_success = True
        messages: list[str] = []

        for file_path in task.file_paths:
            try:
                success, msg = self._process_single(file_path, task, dst_backend)
                if not success:
                    total_success = False
                    messages.append(msg)
            except ValidationError as e:
                total_success = False
                messages.append(e.message)
                log.error(f"[Pipeline]处理失败：{file_path}，{e.message}")
            except Exception as e:
                total_success = False
                messages.append(str(e))
                log.error(f"[Pipeline]处理失败：{file_path}，{e}")

        final_msg = "; ".join(messages) if messages else "处理完成"

        # ---------- 3. 来源特定后处理 ----------
        if task.post_process:
            try:
                task.post_process(task, total_success, final_msg)
            except Exception as e:
                log.error(f"[Pipeline]后处理失败：{e}")

        return total_success, final_msg

    def _process_single(
        self, file_path: str, task: TransferTask, dst_backend: StorageBackend | None
    ) -> tuple[bool, str]:
        """处理单个文件/目录。"""
        # 根据来源类型映射 in_from
        in_from = self._map_source_type(task.source_type, task.source_id)

        # 调用 FileTransferService 执行转移
        success, msg = self._filetransfer.transfer_media(
            in_from=in_from,
            in_path=file_path,
            operation=task.operation,
            target_dir=task.target_dir,
            unknown_dir=task.unknown_dir,
            tmdb_info=task.tmdb_info,
            media_type=task.media_type,
            season=task.season,
            episode=task.episode,
            fallback_episode=task.fallback_episode,
            dst_backend=dst_backend,
        )

        if not success:
            return False, msg

        # ---------- 写入黑名单（所有来源统一） ----------
        self._blacklist.insert(file_path)

        # ---------- 刮削（异步提交，转移不阻塞；下载器来源由 FileTransferService 异步刮削） ----------
        if task.source_type == SourceType.DIRECTORY and task.target_dir:
            self._scrape_after_transfer(task.target_dir, task, dst_backend)

        return True, msg

    def _scrape_after_transfer(self, target_path: str, task: TransferTask, dst_backend: StorageBackend | None) -> None:
        """转移成功后触发异步刮削（仅目录同步场景使用）."""
        scrape_path = target_path
        if os.path.isfile(scrape_path):
            scrape_path = os.path.dirname(scrape_path)

        # 如果目标路径不是媒体库路径，跳过刮削
        if not self._is_media_library_path(scrape_path):
            return

        self._scrape_queue_service.submit_folder_scrape(path=scrape_path, mode="force_all", dst_backend=dst_backend)

    def _is_media_library_path(self, path: str) -> bool:
        """检查路径是否属于媒体库。"""
        if not path:
            return False
        media = settings.get("media")
        if not media:
            return False
        norm_path = os.path.normpath(path) + os.sep
        for key in ("movie_path", "tv_path", "anime_path"):
            val = media.get(key)
            if not val:
                continue
            paths = val if isinstance(val, list) else [val]
            for lib_path in paths:
                lib_norm = os.path.normpath(lib_path) + os.sep
                if norm_path == lib_norm or norm_path.startswith(lib_norm):
                    return True
        return False

    def _resolve_backend(self, backend_id: str) -> StorageBackend | None:
        """根据 backend_id 解析存储后端。"""
        if not backend_id or backend_id == "local":
            return None
        entity = self._backend_repo.get_by_id(int(backend_id))
        if not entity:
            log.warn(f"[Pipeline]未找到后端：{backend_id}")
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

    @staticmethod
    def _map_source_type(source_type: SourceType, source_id: str) -> Any:
        """将 SourceType 映射为 FileTransferService 的 in_from 值。"""
        if source_type == SourceType.DIRECTORY:
            return SyncType.MON
        if source_type == SourceType.DOWNLOADER:
            return source_id or "downloader"
        return SyncType.MAN
