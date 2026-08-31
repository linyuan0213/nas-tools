import os
from typing import Any

import log
from app.core.exceptions import InfrastructureError, NetworkError
from app.downloader.client._base import _IDownloadClient
from app.downloader.schema import ConfigField, DownloaderConfigSchema
from app.downloader.strategy import RemoveStrategy
from app.schemas.download import Torrent, TorrentStatus
from app.utils import ExceptionUtils

from .pythunder import PyThunder


class Thunder(_IDownloadClient):
    client_id = "thunder"
    client_type = "thunder"
    client_name = "迅雷"
    supports_pt = False  # 迅雷不支持 PT 私有站点种子

    config_schema = DownloaderConfigSchema(
        name="迅雷",
        monitor_enable=True,
        speedlimit_enable=False,
        fields=[
            ConfigField(
                id="host",
                required=True,
                title="IP地址",
                tooltip="配置迅雷NAS设备的IP地址",
                type="text",
                placeholder="192.168.1.100",
            ),
            ConfigField(
                id="port",
                required=True,
                title="端口",
                tooltip="迅雷NAS Web管理端口，默认为2345",
                type="text",
                placeholder="2345",
                default="2345",
            ),
            ConfigField(
                id="token",
                required=False,
                title="认证令牌",
                tooltip="迅雷认证令牌，默认为Basic认证，格式为Basic base64(username:password)",
                type="text",
                placeholder="Basic bGlueXVhbjIxMzpMeTE5OTYwMjEzKio=",
            ),
        ],
    )

    _client_config: dict = {}
    _client = None
    host = None
    port = None
    token = None
    download_dir: list = []
    _recreated_tasks: dict[str, str] = {}

    def __init__(self, config: dict | None = None):
        if config:
            self._client_config = config
        self.init_config()
        self.connect()

    def init_config(self) -> None:
        if self._client_config:
            self.host = self._client_config.get("host")
            self.port = self._client_config.get("port")
            self.token = self._client_config.get("token")
            self.download_dir = self._client_config.get("download_dir") or []
            if self.host and self.port:
                self._client = PyThunder(host=self.host, port=self.port, token=self.token)

    def connect(self) -> None:
        pass

    def get_status(self) -> bool:
        if not self._client:
            return False
        try:
            device_id = self._client.get_device_id()
            return bool(device_id)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]连接测试失败: {e!s}")
            return False

    def get_torrents(
        self, ids: list[str] | str | None = None, status: Any = None, tag: str | list[str] | None = None
    ) -> tuple[list[Torrent], bool]:
        if not self._client:
            return [], True
        try:
            if status == "downloading":
                tasks = self._client.get_downloading_tasks()
            elif status == "completed":
                tasks = self._client.get_complete_tasks()
            else:
                downloading_tasks = self._client.get_downloading_tasks()
                complete_tasks = self._client.get_complete_tasks()
                tasks = downloading_tasks + complete_tasks

            torrent_list: list[Torrent] = []
            for task in tasks:
                torrent = self._task_to_torrent(task)
                if torrent:
                    torrent_list.append(torrent)
            return torrent_list, False
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]获取任务列表失败: {e!s}")
            return [], True

    def get_downloading_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        statuses = [
            TorrentStatus.Downloading,
            TorrentStatus.Paused,
            TorrentStatus.Queued,
            TorrentStatus.Checking,
            TorrentStatus.Pending,
        ]
        torrents, error = self.get_torrents(ids=ids, status=statuses, tag=tag)
        torrents = [t for t in torrents if t.progress * 100 < 100]
        return None if error else torrents

    def get_completed_torrents(
        self, ids: list[str] | str | None = None, tag: str | list[str] | None = None
    ) -> list[Torrent] | None:
        torrents, error = self.get_torrents(status="completed")
        return None if error else torrents

    def _normalize_files(self, raw_files: list[dict]) -> list[dict]:
        return raw_files

    def _resolve_tid(self, tid: str | None) -> str | None:
        if tid and tid in self._recreated_tasks:
            return self._recreated_tasks[tid]
        return tid

    def _get_task_by_id(self, tid: str) -> dict | None:
        if not self._client:
            return None
        try:
            tasks = self._client.get_downloading_tasks(limit=1000) + self._client.get_complete_tasks(limit=1000)
            for task in tasks:
                if task.get("id") == tid:
                    return task
        except Exception as e:
            log.error(f"[{self.client_name}]查找任务失败: {e!s}")
        return None

    def get_files(self, tid: str | None = None) -> list[dict] | None:
        if not self._client or not tid:
            return None
        try:
            task = self._get_task_by_id(tid)
            if not task:
                return None
            params = task.get("params", {})
            download_url = params.get("url", "")
            if not download_url:
                return None
            torrent_info = self._client.get_torrent_info(download_url, extract_info=True)
            if not torrent_info or "files" not in torrent_info:
                return None
            return [
                {
                    "id": f.get("file_index", 0),
                    "name": f.get("name", ""),
                    "size": f.get("size_bytes", 0),
                }
                for f in torrent_info["files"]
            ]
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]获取文件列表失败: {e!s}")
            return None

    def set_file_selection(self, tid: str | None, selected_map: dict[int, bool]) -> bool:
        if not self._client or not tid:
            return True
        try:
            task = self._get_task_by_id(tid)
            if not task:
                return False
            params = task.get("params", {})
            download_url = params.get("url", "")
            save_path = params.get("parent_folder_path", "/downloads/xunlei/")
            if not download_url:
                return False

            selected_indices = [str(fid) for fid, selected in selected_map.items() if selected]
            if not selected_indices:
                return False
            file_indices = ",".join(selected_indices)

            self._client.delete_task(tid, delete_files=False)

            folder_id = self._client._resolve_folder_id(save_path)
            task_info = self._client.download(
                download_urls=download_url,
                destination_path=save_path,
                parent_folder_id=folder_id,
                file_indices=file_indices,
            )
            new_tid = task_info.get("id") if task_info else None
            if new_tid:
                self._recreated_tasks[tid] = str(new_tid)
                log.info(f"[{self.client_name}]任务 {tid} 已拆包重建为 {new_tid}，选中文件: {file_indices}")
                return True
            return False
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]设置文件选择失败: {e!s}")
            return False

    def set_torrents_status(self, ids: list[str] | str, tags: str | list[str] | None = None) -> bool:
        return True

    def set_torrents_tag(self, ids: list[str] | str | None = None, tags: str | list[str] | None = None) -> bool:
        return True

    def get_remove_torrents(self, strategy: RemoveStrategy) -> list[dict]:
        return []

    def add_torrent(self, content: str | bytes, **kwargs) -> bool:
        result = self.add_torrent_and_get_id(content, **kwargs)
        return result is not None and result != ""

    def add_torrent_and_get_id(
        self,
        content: str | bytes,
        is_paused: bool = False,
        download_dir: str | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        upload_limit: int | None = None,
        download_limit: int | None = None,
        ratio_limit: float | None = None,
        seeding_time_limit: int | None = None,
        cookie: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        if not self._client:
            return None
        try:
            if isinstance(content, str):
                if content.startswith("magnet:"):
                    download_url = content
                elif content.endswith(".torrent") or os.path.exists(content):
                    magnet_url = self._client.torrent_to_magnet(content)
                    if not magnet_url:
                        log.error("[{self.client_name}]种子文件转换磁力链接失败")
                        return None
                    download_url = magnet_url
                else:
                    download_url = content
            else:
                log.error("[{self.client_name}]不支持二进制种子内容")
                return None

            folder_id = self._client._resolve_folder_id(download_dir or "/downloads/xunlei/")
            file_indices = kwargs.get("file_indices")
            file_names = kwargs.get("file_names")
            task_info = self._client.download(
                download_urls=download_url,
                destination_path=download_dir or "/downloads/xunlei/",
                parent_folder_id=folder_id,
                file_indices=file_indices,
                file_names=file_names,
            )
            task_id = task_info.get("id") if task_info else None
            return str(task_id) if task_id else None
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]添加下载任务失败: {e!s}")
            ExceptionUtils.exception_traceback(e)
            return None

    def start_torrents(self, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            if ids is None:
                return False
            if not isinstance(ids, list):
                ids = [ids]
            success = True
            for task_id in ids:
                resolved = self._resolve_tid(task_id)
                result = self._client.resume_task(str(resolved))
                if not result:
                    success = False
            return success
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]启动任务失败: {e!s}")
            return False

    def stop_torrents(self, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            if ids is None:
                return False
            if not isinstance(ids, list):
                ids = [ids]
            success = True
            for task_id in ids:
                resolved = self._resolve_tid(task_id)
                result = self._client.pause_task(str(resolved))
                if not result:
                    success = False
            return success
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]暂停任务失败: {e!s}")
            return False

    def delete_torrents(self, delete_file: bool = False, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            if ids is None:
                return False
            if not isinstance(ids, list):
                ids = [ids]
            success = True
            for task_id in ids:
                resolved = self._resolve_tid(task_id)
                result = self._client.delete_task(str(resolved), delete_files=bool(delete_file))
                if not result:
                    success = False
            return success
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]删除任务失败: {e!s}")
            return False

    def get_download_dirs(self) -> list[str]:
        return self.download_dir

    def change_torrent(self, tid: str | None = None, **kwargs: Any) -> bool:
        return True

    def set_speed_limit(self, download_limit: int | None = None, upload_limit: int | None = None) -> bool:
        return True

    def recheck_torrents(self, ids: list[str] | str | None = None) -> bool:
        return True

    def get_free_space(self, path: str) -> int | None:
        return 0

    def _map_status(self, raw_state: str) -> TorrentStatus:
        mapping = {
            "PHASE_TYPE_COMPLETE": TorrentStatus.Uploading,
            "PHASE_TYPE_RUNNING": TorrentStatus.Downloading,
            "PHASE_TYPE_PENDING": TorrentStatus.Downloading,
            "PHASE_TYPE_PAUSED": TorrentStatus.Stopped,
            "PHASE_TYPE_ERROR": TorrentStatus.Error,
        }
        return mapping.get(raw_state, TorrentStatus.Unknown)

    @property
    def _supported_statuses(self) -> list[TorrentStatus]:
        return [
            TorrentStatus.Downloading,
            TorrentStatus.Uploading,
            TorrentStatus.Stopped,
            TorrentStatus.Error,
            TorrentStatus.Unknown,
        ]

    def _task_to_torrent(self, task: dict[str, Any]) -> Torrent | None:
        try:
            torrent = Torrent()
            torrent.id = task.get("id", "")
            torrent.name = task.get("name", "")
            file_size = task.get("file_size", 0)
            if isinstance(file_size, str):
                try:
                    torrent.size = int(file_size)
                except ValueError:
                    torrent.size = 0
            else:
                torrent.size = file_size

            phase = task.get("phase", "")
            progress = task.get("progress", 0)
            if isinstance(progress, (int, float)):
                torrent.progress = round(progress / 100.0, 2)
            else:
                torrent.progress = 0.0

            if phase == "PHASE_TYPE_COMPLETE":
                torrent.status = TorrentStatus.Uploading
                torrent.downloaded = torrent.size
                torrent.progress = 1.0
            elif phase in ["PHASE_TYPE_RUNNING", "PHASE_TYPE_PENDING"]:
                torrent.status = TorrentStatus.Downloading
                torrent.downloaded = int(torrent.size * torrent.progress)
            elif phase == "PHASE_TYPE_PAUSED":
                torrent.status = TorrentStatus.Stopped
            elif phase == "PHASE_TYPE_ERROR":
                torrent.status = TorrentStatus.Error
            else:
                torrent.status = TorrentStatus.Unknown

            params = task.get("params", {})
            speed_str = params.get("speed", "0")
            try:
                torrent.download_speed = int(float(speed_str))
            except (ValueError, TypeError):
                torrent.download_speed = 0

            torrent.upload_speed = 0
            torrent.save_path = params.get("parent_folder_path", "")
            return torrent
        except (InfrastructureError, NetworkError):
            raise
        except Exception as e:
            log.error(f"[{self.client_name}]转换任务信息失败: {e!s}")
            return None
