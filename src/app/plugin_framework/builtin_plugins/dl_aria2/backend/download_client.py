import re
from typing import Any

from app.core.exceptions import InfrastructureError, NetworkError
from app.downloader.client._base import _IDownloadClient
from app.downloader.schema import ConfigField, DownloaderConfigSchema
from app.downloader.strategy import RemoveStrategy
from app.infrastructure.http.client import HttpClient
from app.schemas.download import Torrent, TorrentStatus
from app.utils import ExceptionUtils

from .pyaria2 import PyAria2


class Aria2(_IDownloadClient):
    client_id = "aria2"
    client_type = "aria2"
    client_name = "Aria2"
    supports_pt = False  # Aria2 不支持 PT 私有站点种子

    config_schema = DownloaderConfigSchema(
        name="Aria2",
        monitor_enable=True,
        fields=[
            ConfigField(
                id="host",
                required=True,
                title="IP地址",
                tooltip="配置IP地址，如为https则需要增加https://前缀",
                type="text",
                placeholder="127.0.0.1",
            ),
            ConfigField(id="port", required=True, title="端口", type="text", placeholder="6800"),
            ConfigField(id="secret", required=True, title="令牌", type="text", placeholder=""),
        ],
    )

    _client_config: dict = {}
    _client = None
    host = None
    port = None
    secret = None
    download_dir: list = []

    def __init__(self, config: dict | None = None):
        if config:
            self._client_config = config
        self.init_config()
        self.connect()

    def init_config(self) -> None:
        if self._client_config:
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith("http"):
                    self.host = "http://" + self.host
                self.host = self.host.removesuffix("/")
            self.port = self._client_config.get("port")
            self.secret = self._client_config.get("secret")
            self.download_dir = self._client_config.get("download_dir") or []
            if self.host and self.port:
                self._client = PyAria2(secret=self.secret, host=self.host, port=self.port)

    def connect(self) -> None:
        pass

    def get_status(self) -> bool:
        if not self._client:
            return False
        ver = self._client.getVersion()
        return bool(ver)

    def get_torrents(
        self, ids: list[str] | str | None = None, status: Any = None, tag: str | list[str] | None = None
    ) -> tuple[list[Torrent], bool]:
        if not self._client:
            return [], True
        ret_torrents = []
        if ids:
            if isinstance(ids, list):
                for gid in ids:
                    ret_torrents.append(self._client.tellStatus(gid=gid))
            else:
                ret_torrents = [self._client.tellStatus(gid=ids)]
        elif status:
            if status == "downloading":
                active = self._client.tellActive()
                waiting = self._client.tellWaiting(offset=-1, num=100)
                ret_torrents = (active if isinstance(active, list) else []) + (
                    waiting if isinstance(waiting, list) else []
                )
            else:
                ret_torrents = self._client.tellStopped(offset=-1, num=1000)

        torrent_list: list[Torrent] = []
        for torrent in ret_torrents if isinstance(ret_torrents, list) else []:
            if isinstance(torrent, dict):
                torrent_list.append(self.torrent_properties(torrent=torrent))
        return torrent_list, False

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

    def set_torrents_status(self, ids: list[str] | str, tags: str | list[str] | None = None) -> bool:
        return bool(self.delete_torrents(ids=ids, delete_file=False))

    def set_torrents_tag(self, ids: list[str] | str | None = None, tags: str | list[str] | None = None) -> bool:
        return True

    def get_remove_torrents(self, strategy: RemoveStrategy) -> list[dict]:
        return []

    def add_torrent(self, content: str | bytes, **kwargs) -> bool:
        download_dir = kwargs.get("download_dir")
        if not self._client:
            return False
        try:
            if isinstance(content, str):
                if re.match("^https*://", content):
                    try:
                        p = HttpClient().get(content, follow_redirects=False)
                        if p.headers.get("Location"):
                            content = p.headers.get("Location") or ""
                    except (InfrastructureError, NetworkError):
                        raise
                    except Exception as result:
                        ExceptionUtils.exception_traceback(result)
                result = self._client.addUri(uris=[content], options={"dir": download_dir})
                return bool(result)
            else:
                result = self._client.addTorrent(torrent=content, uris=[], options={"dir": download_dir})
                return bool(result)
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def start_torrents(self, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            return bool(self._client.unpause(gid=ids))
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def stop_torrents(self, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            return bool(self._client.pause(gid=ids))
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def delete_torrents(self, delete_file: bool = False, ids: list[str] | str | None = None) -> bool:
        if not self._client:
            return False
        try:
            return bool(self._client.forceRemove(gid=ids))
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def get_download_dirs(self) -> list[str]:
        return []

    def list_remote_dirs(self) -> list[str]:
        """Aria2 仅支持读取全局默认下载目录"""
        if not self._client:
            return []
        try:
            options = self._client.getGlobalOption()
            if isinstance(options, dict) and options.get("dir"):
                return [str(options["dir"])]
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        return []

    def change_torrent(self, tid: str | None = None, **kwargs: Any) -> bool:
        return True

    def set_speed_limit(self, download_limit: int | None = None, upload_limit: int | None = None) -> bool:
        if not self._client:
            return False
        dl_limit = int(download_limit or 0) * 1024
        ul_limit = int(upload_limit or 0) * 1024
        try:
            speed_opt = self._client.getGlobalOption()
            if not isinstance(speed_opt, dict):
                return False
            if speed_opt.get("max-overall-upload-limit") != ul_limit:
                speed_opt["max-overall-upload-limit"] = ul_limit
            if speed_opt.get("max-overall-download-limit") != dl_limit:
                speed_opt["max-overall-download-limit"] = dl_limit
            return bool(self._client.changeGlobalOption(speed_opt))
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return False

    def _normalize_files(self, raw_files: list[dict]) -> list[dict]:
        return [{"id": i, "name": f.get("path", "").split("/")[-1]} for i, f in enumerate(raw_files)]

    def set_file_selection(self, tid: str | None, selected_map: dict[int, bool]) -> bool:
        return True

    def get_files(self, tid: str | None = None) -> list[dict] | None:
        if not self._client:
            return None
        try:
            files = self._client.getFiles(gid=tid)
            return files if isinstance(files, list) else None
        except (InfrastructureError, NetworkError):
            raise
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def recheck_torrents(self, ids: list[str] | str | None = None) -> bool:
        return True

    def get_free_space(self, path: str) -> int | None:
        return None

    def torrent_properties(self, torrent: dict) -> Torrent:
        torrent_obj = Torrent()
        torrent_obj.id = torrent.get("gid")
        torrent_obj.name = torrent.get("bittorrent", {}).get("info", {}).get("name")
        torrent_obj.size = int(torrent.get("totalLength") or 0)
        torrent_obj.downloaded = int(torrent.get("completedLength") or 0)
        torrent_obj.status = self._map_status(torrent.get("status") or "")
        torrent_obj.download_speed = int(torrent.get("downloadSpeed") or 0)
        torrent_obj.upload_speed = int(torrent.get("uploadSpeed") or 0)
        total = int(torrent.get("totalLength") or 0)
        completed = int(torrent.get("completedLength") or 0)
        torrent_obj.progress = round(completed / total, 1) if total else 0.0
        torrent_obj.save_path = torrent.get("dir")
        return torrent_obj

    def _map_status(self, raw_state: str) -> TorrentStatus:
        mapping = {
            "paused": TorrentStatus.Stopped,
            "downloading": TorrentStatus.Downloading,
            "completed": TorrentStatus.Uploading,
            "UNKNOWN": TorrentStatus.Unknown,
        }
        return mapping.get(raw_state, TorrentStatus.Unknown)

    @property
    def _supported_statuses(self) -> list[TorrentStatus]:
        return [
            TorrentStatus.Downloading,
            TorrentStatus.Uploading,
            TorrentStatus.Stopped,
            TorrentStatus.Unknown,
        ]
