"""WebDAV 存储后端（基于 httpx 自实现）。"""

from collections.abc import Iterator
from email.utils import parsedate_to_datetime
from typing import BinaryIO

import defusedxml.ElementTree as ET  # type: ignore[import-untyped]
import httpx2

import log
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class WebDAVStorageBackend(StorageBackend):
    """WebDAV 存储后端。"""

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)
        self._url = getattr(config, "url", "").rstrip("/")
        self._client = HttpClient(
            config=HttpClientConfig(
                verify_ssl=getattr(config, "ssl_verify", True),
                auth=httpx2.BasicAuth(
                    getattr(config, "username", ""),
                    getattr(config, "password", ""),
                ),
                default_headers={"Depth": "1"},
            )
        )

    def _req(self, method: str, path: str, **kwargs):
        url = self._url + "/" + path.lstrip("/")
        return self._client.request(method, url, **kwargs)

    def exists(self, path: str) -> bool:
        try:
            self._req("HEAD", path)
            return True
        except Exception:
            return False

    def stat(self, path: str) -> FileInfo | None:
        try:
            resp = self._req("PROPFIND", path, headers={"Depth": "0"})
            root = ET.fromstring(resp.content)
            return self._parse_prop(root, path)
        except Exception:
            return None

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        resp = self._req("PROPFIND", path, headers={"Depth": "1"})
        root = ET.fromstring(resp.content)
        ns = {"d": "DAV:"}
        self_href = path.lstrip("/")
        for response in root.findall("d:response", ns):
            href = response.findtext("d:href", "", ns).lstrip("/")
            if href == self_href or href.rstrip("/") == self_href.rstrip("/"):
                continue
            yield self._parse_prop(response, href)

    def _parse_prop(self, elem, path: str) -> FileInfo:
        ns = {"d": "DAV:"}
        prop = elem.find(".//d:prop", ns)
        size = 0
        mtime = 0
        is_dir = False
        if prop is not None:
            size_str = prop.findtext("d:getcontentlength", "0", ns)
            size = int(size_str) if size_str else 0
            mtime_str = prop.findtext("d:getlastmodified", "", ns)
            if mtime_str:
                try:
                    mtime = parsedate_to_datetime(mtime_str).timestamp()
                except Exception:
                    mtime = 0
            res_type = prop.find("d:resourcetype", ns)
            is_dir = res_type is not None and res_type.find("d:collection", ns) is not None
        return FileInfo(path=path, size=size, mtime=mtime, is_dir=is_dir)

    def read_stream(self, path: str) -> BinaryIO:
        return self._client.stream("GET", self._url + "/" + path.lstrip("/"))

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        # httpx content 接受文件对象，会按内部缓冲区流式上传；chunk_size 预留用于后续细粒度控制
        self._req("PUT", path, content=stream)

    def mkdir(self, path: str, parents: bool = True) -> None:
        try:
            self._req("MKCOL", path)
        except Exception:
            if not parents:
                raise
            parts = path.strip("/").split("/")
            for i in range(1, len(parts) + 1):
                sub = "/" + "/".join(parts[:i])
                try:
                    self._req("MKCOL", sub)
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[WebDAVStorageBackend]创建目录失败 {sub}: {e}")

    def remove(self, path: str, recursive: bool = False) -> None:
        if recursive:
            for child in self.list_dir(path):
                self.remove(child.path, recursive=True)
        self._req("DELETE", path)

    def copy(self, src: str, dst: str) -> None:
        dst_url = self._url + "/" + dst.lstrip("/")
        self._req("COPY", src, headers={"Destination": dst_url})

    def move(self, src: str, dst: str) -> None:
        dst_url = self._url + "/" + dst.lstrip("/")
        self._req("MOVE", src, headers={"Destination": dst_url})

    def health_check(self) -> tuple[bool, str]:
        try:
            self._req("OPTIONS", "/")
            return True, "连接成功"
        except Exception as e:
            return False, str(e)
