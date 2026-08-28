"""SMB 存储后端。"""

import shutil
from collections.abc import Iterator
from typing import BinaryIO

from smbclient import (
    copyfile,
    makedirs,
    mkdir,
    open_file,
    register_session,
    remove,
    rename,
    rmdir,
    scandir,
)
from smbclient import stat as smb_stat
from smbclient.path import exists as smb_exists
from smbclient.path import isdir
from smbclient.shutil import rmtree

import log
from app.storage.backends.base import FileInfo, StorageBackend, StorageConfig


class SMBStorageBackend(StorageBackend):
    """SMB 存储后端。"""

    def __init__(self, config: StorageConfig) -> None:
        super().__init__(config)
        self._server = getattr(config, "server", "")
        self._share = (getattr(config, "share", "") or "").lstrip("/\\")
        if not self._server or not self._share:
            raise ValueError("SMB server 和 share 不能为空")
        self._username = getattr(config, "username", "")
        self._password = getattr(config, "password", "")
        self._port = int(getattr(config, "port", 445) or 445)
        self._base = f"\\\\{self._server}\\{self._share}"
        if self._username:
            register_session(
                self._server,
                username=self._username,
                password=self._password,
                port=self._port,
            )

    def _path(self, path: str) -> str:
        p = path.lstrip("/").replace("/", "\\")
        if p:
            return f"{self._base}\\{p}"
        return self._base

    def _kw(self) -> dict:
        """smbclient 连接参数：显式传递端口（非 445 时必须）"""
        return {"port": self._port}

    def exists(self, path: str) -> bool:
        return smb_exists(self._path(path), **self._kw())

    def stat(self, path: str) -> FileInfo | None:
        try:
            st = smb_stat(self._path(path), **self._kw())
            return FileInfo(
                path=path,
                size=st.st_size,
                mtime=st.st_mtime,
                is_dir=isdir(self._path(path), **self._kw()),
            )
        except Exception:
            return None

    def list_dir(self, path: str) -> Iterator[FileInfo]:
        rp = self._path(path)
        for entry in scandir(rp, **self._kw()):
            epath = path.rstrip("/") + "/" + entry.name
            # entry.stat() 不透传端口（非 445 会连错端口），用后端 stat 取元信息
            st = self.stat(epath)
            yield FileInfo(
                path=epath,
                size=st.size if st else 0,
                mtime=st.mtime if st else 0,
                is_dir=st.is_dir if st else entry.is_dir(),
            )

    def read_stream(self, path: str) -> BinaryIO:
        return open_file(self._path(path), mode="rb", **self._kw())

    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        rp = self._path(path)
        self._ensure_dir(self._dir(rp))
        # 如果目标路径已存在且是目录（之前失败遗留），强制删除
        if isdir(rp, **self._kw()):
            try:
                rmdir(rp, **self._kw())
            except Exception as e:  # noqa: BLE001
                log.debug(f"[smb]忽略异常: {e}")
        length = chunk_size if chunk_size > 0 else 1024 * 1024
        try:
            with open_file(rp, mode="wb", **self._kw()) as f:
                shutil.copyfileobj(stream, f, length=length)
        except Exception as e:
            if "Is a directory" in str(e) or getattr(e, "errno", None) == 21:
                log.warn(f"SMB 目标路径 {rp} 是目录，强制删除后重试写入")
                rmtree(rp, **self._kw())
                with open_file(rp, mode="wb", **self._kw()) as f:
                    shutil.copyfileobj(stream, f, length=length)
            else:
                raise

    def _dir(self, path: str) -> str:
        return path.rsplit("\\", 1)[0] if "\\" in path else path

    def _ensure_dir(self, path: str) -> None:
        """逐层创建 SMB 目录，避免 makedirs 在 Linux 上处理反斜杠路径的问题。"""
        if not path or path == self._base:
            return
        if smb_exists(path, **self._kw()) and isdir(path, **self._kw()):
            return
        # 先确保父目录存在
        parent = self._dir(path)
        if parent and parent != path and parent != self._base:
            self._ensure_dir(parent)
        try:
            mkdir(path, **self._kw())
        except Exception:
            # 目录可能已存在（race condition）
            if not (smb_exists(path, **self._kw()) and isdir(path, **self._kw())):
                raise

    def mkdir(self, path: str, parents: bool = True) -> None:
        rp = self._path(path)
        if parents:
            makedirs(rp, exist_ok=True, **self._kw())
        else:
            mkdir(rp, **self._kw())

    def remove(self, path: str, recursive: bool = False) -> None:
        norm = path.replace("\\", "/").strip("/")
        if not norm:
            raise ValueError("不能删除 SMB share 根目录")
        rp = self._path(path)
        if isdir(rp, **self._kw()):
            if recursive:
                rmtree(rp, **self._kw())
            else:
                rmdir(rp, **self._kw())
        else:
            remove(rp, **self._kw())

    def copy(self, src: str, dst: str) -> None:
        copyfile(self._path(src), self._path(dst), **self._kw())

    def move(self, src: str, dst: str) -> None:
        # 服务端重命名（标准 shutil.move 无法处理 UNC 路径）
        rename(self._path(src), self._path(dst), **self._kw())

    def health_check(self) -> tuple[bool, str]:
        try:
            for _ in self.list_dir("/"):
                break
            return True, "连接成功"
        except Exception as e:
            return False, str(e)
