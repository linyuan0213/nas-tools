"""OpenList / AList 存储后端。"""

import datetime
import posixpath
from collections.abc import Iterator
from typing import BinaryIO
from urllib.parse import quote

from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class OpenListStorageBackend(StorageBackend):
    """OpenList 存储后端。

    参考 API: https://fox.oplist.org/
    认证: 支持直接填 token 或 username/password 登录获取 JWT。
    """

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)
        self._base = getattr(config, "base_url", "").rstrip("/")
        self._token = getattr(config, "api_token", "")
        self._username = getattr(config, "username", "")
        self._password = getattr(config, "password", "")
        self._write_enabled = getattr(config, "write_enabled", False)
        self._http = HttpClient(HttpClientConfig(timeout=30.0, connect_timeout=10.0))
        if not self._token and self._username and self._password:
            self._login()

    def _login(self) -> None:
        """通过 username/password 获取 JWT token。"""
        url = f"{self._base}/api/auth/login"
        resp = self._http.post(
            url,
            json={"username": self._username, "password": self._password},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(data.get("message", "login failed"))
        self._token = data["data"]["token"]

    def _auth_headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": self._token}
        return {}

    def _api(self, endpoint: str, method: str = "POST", **kwargs):
        url = f"{self._base}/api/fs/{endpoint.lstrip('/')}"
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}
        resp = self._http.request(method, url, timeout=30, headers=headers, **kwargs)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(data.get("message", "unknown error"))
        return data.get("data", {})

    @staticmethod
    def _parse_mtime(value) -> float:
        """解析 OpenList 返回的 modified/created 时间为 Unix 时间戳。"""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0

    def exists(self, path: str) -> bool:
        try:
            return self.stat(path) is not None
        except Exception:
            return False

    def stat(self, path: str) -> FileInfo | None:
        try:
            data = self._api("get", json={"path": path, "password": ""})
            return FileInfo(
                path=path,
                size=int(data.get("size", 0) or 0),
                mtime=self._parse_mtime(data.get("modified")),
                is_dir=bool(data.get("is_dir", False)),
            )
        except Exception:
            return None

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        page = 1
        per_page = 100
        while True:
            data = self._api(
                "list",
                json={"path": path, "password": "", "page": page, "per_page": per_page},
            )
            items = data.get("content") or []
            for item in items:
                yield FileInfo(
                    path=posixpath.join(path.rstrip("/"), item.get("name", "")),
                    size=int(item.get("size", 0) or 0),
                    mtime=self._parse_mtime(item.get("modified")),
                    is_dir=bool(item.get("is_dir", False)),
                )
            if len(items) < per_page:
                break
            page += 1

    def read_stream(self, path: str) -> BinaryIO:
        data = self._api("get", json={"path": path, "password": ""})
        raw_url = data.get("raw_url") or data.get("url")
        if not raw_url:
            raise RuntimeError("无法获取文件下载地址")
        return self._http.stream("GET", raw_url, timeout=60)

    def _get_stream_size(self, stream: BinaryIO) -> int:
        """尝试获取流的大小。"""
        try:
            pos = stream.tell()
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(pos)
            return size
        except Exception:
            return 0

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        if not self._write_enabled:
            raise NotImplementedError("OpenList 后端未启用写入")
        url = f"{self._base}/api/fs/put"
        # HTTP 头不支持非 latin1 字符，中文路径需 URL 编码（AList 端会自动解码）
        headers = {"File-Path": quote(path, safe="/")}
        actual_size = size or self._get_stream_size(stream)
        if actual_size > 0:
            headers["Content-Length"] = str(actual_size)
        headers = {**self._auth_headers(), **headers}
        resp = self._http.put(url, headers=headers, content=stream, timeout=300)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(data.get("message", "upload failed"))

    def mkdir(self, path: str, parents: bool = True) -> None:
        if not self._write_enabled:
            raise NotImplementedError("OpenList 后端未启用写入")
        self._api("mkdir", json={"path": path})

    def remove(self, path: str, recursive: bool = False) -> None:
        if not self._write_enabled:
            raise NotImplementedError("OpenList 后端未启用写入")
        parent = posixpath.dirname(path.rstrip("/"))
        name = posixpath.basename(path.rstrip("/"))
        self._api("remove", json={"dir": parent, "names": [name]})

    def copy(self, src: str, dst: str) -> None:
        if not self._write_enabled:
            raise NotImplementedError("OpenList 后端未启用写入")
        src_dir = posixpath.dirname(src.rstrip("/"))
        dst_dir = posixpath.dirname(dst.rstrip("/"))
        name = posixpath.basename(src.rstrip("/"))
        self._api(
            "copy",
            json={
                "src_dir": src_dir,
                "dst_dir": dst_dir,
                "names": [name],
            },
        )
        # AList copy 仅支持同名复制，目标名不同时需再 rename
        target = posixpath.basename(dst.rstrip("/"))
        if target and target != name:
            self._api("rename", json={"path": f"{dst_dir.rstrip('/')}/{name}", "name": target})

    def move(self, src: str, dst: str) -> None:
        if not self._write_enabled:
            raise NotImplementedError("OpenList 后端未启用写入")
        src_dir = posixpath.dirname(src.rstrip("/"))
        dst_dir = posixpath.dirname(dst.rstrip("/"))
        name = posixpath.basename(src.rstrip("/"))
        self._api(
            "move",
            json={
                "src_dir": src_dir,
                "dst_dir": dst_dir,
                "names": [name],
            },
        )
        # AList move 仅支持同名移动，目标名不同时需再 rename
        target = posixpath.basename(dst.rstrip("/"))
        if target and target != name:
            self._api("rename", json={"path": f"{dst_dir.rstrip('/')}/{name}", "name": target})

    def health_check(self) -> tuple[bool, str]:
        try:
            self._api("list", json={"path": "/", "password": ""})
            return True, "连接成功"
        except Exception as e:
            # 连接/认证成功但未配置存储挂载时提示而非报错
            if "storage not found" in str(e):
                return True, "连接成功（未配置存储挂载）"
            return False, str(e)
