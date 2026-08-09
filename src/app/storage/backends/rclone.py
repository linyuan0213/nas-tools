"""Rclone 存储后端。

基于 rclone rc HTTP API 实现，要求 rclone 已以 daemon 模式运行
（如 rclone rcd --rc-no-auth 或配置了 rc-user/rc-pass）。
"""

import os
from collections.abc import Iterator
from typing import BinaryIO

import httpx2

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class RcloneStorageBackend(StorageBackend):
    """
    Rclone 存储后端。

    通过 rclone rc HTTP API 操作，不依赖本地 rclone 命令。
    用户需先启动 rclone rc daemon：
        rclone rcd --rc-no-auth
    或
        rclone rcd --rc-user=admin --rc-pass=***
    """

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)
        self._rc_url = (getattr(config, "rc_url", "") or "http://localhost:5572").rstrip("/")
        self._remote = getattr(config, "remote_name", "NEXUS_MEDIA")
        username = getattr(config, "rc_user", "")
        password = getattr(config, "rc_pass", "")
        auth = httpx2.BasicAuth(username, password) if username else None
        http_config = HttpClientConfig(auth=auth)
        self._client = HttpClient(config=http_config)

    def _fs_path(self, path: str) -> str:
        return f"{self._remote}:{path.lstrip('/')}"

    def _call(self, endpoint: str, payload: dict) -> dict:
        url = f"{self._rc_url}/{endpoint}"
        resp = self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def exists(self, path: str) -> bool:
        try:
            result = self._call("operations/stat", {"fs": self._fs_path(""), "remote": path.lstrip("/")})
            return result.get("item") is not None
        except Exception:
            return False

    def stat(self, path: str) -> FileInfo | None:
        try:
            result = self._call("operations/stat", {"fs": self._fs_path(""), "remote": path.lstrip("/")})
            item = result.get("item")
            if not item:
                return None
            return FileInfo(
                path=path,
                size=item.get("Size", 0),
                mtime=item.get("ModTime", 0),
                is_dir=item.get("IsDir", False),
            )
        except Exception:
            return None

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        result = self._call(
            "operations/list",
            {"fs": self._fs_path(""), "remote": path.lstrip("/"), "opt": {"recurse": False}},
        )
        for item in result.get("list", []):
            yield FileInfo(
                path=os.path.join(path, item.get("Name", "")),
                size=item.get("Size", 0),
                mtime=item.get("ModTime", 0),
                is_dir=item.get("IsDir", False),
            )

    def read_stream(self, path: str) -> BinaryIO:
        raise NotImplementedError("Rclone 后端暂不支持流式读取，请使用 write_stream 上传")

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        raise NotImplementedError("Rclone 后端暂不支持流式写入")

    def mkdir(self, path: str, parents: bool = True) -> None:
        self._call("operations/mkdir", {"fs": self._fs_path(""), "remote": path.lstrip("/")})

    def remove(self, path: str, recursive: bool = False) -> None:
        if recursive:
            self._call("operations/purge", {"fs": self._fs_path(""), "remote": path.lstrip("/")})
        else:
            self._call("operations/deletefile", {"fs": self._fs_path(""), "remote": path.lstrip("/")})

    def copy(self, src: str, dst: str) -> None:
        self._call(
            "operations/copyfile",
            {
                "srcFs": self._fs_path(""),
                "srcRemote": src.lstrip("/"),
                "dstFs": self._fs_path(""),
                "dstRemote": dst.lstrip("/"),
            },
        )

    def move(self, src: str, dst: str) -> None:
        self._call(
            "operations/movefile",
            {
                "srcFs": self._fs_path(""),
                "srcRemote": src.lstrip("/"),
                "dstFs": self._fs_path(""),
                "dstRemote": dst.lstrip("/"),
            },
        )

    def health_check(self) -> tuple[bool, str]:
        try:
            url = f"{self._rc_url}/core/stats"
            resp = self._client.post(url)
            resp.raise_for_status()
            return True, "连接成功"
        except Exception as e:
            return False, str(e)
