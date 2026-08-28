"""存储后端抽象基类。"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import BinaryIO


class StorageType(Enum):
    """支持的存储类型。"""

    LOCAL = auto()
    WEBDAV = auto()
    SMB = auto()
    S3 = auto()
    RCLONE = auto()
    OPENLIST = auto()


@dataclass(frozen=True)
class FileInfo:
    """文件元信息。"""

    path: str
    size: int
    mtime: float
    is_dir: bool
    mime_type: str = ""


@dataclass
class StorageConfig:
    """存储后端配置基类。"""

    id: str
    name: str
    type: StorageType
    enabled: bool = True

    @classmethod
    def get_fields(cls) -> list[dict]:
        """返回该配置类型的表单字段定义。"""
        return []


class StorageBackend(ABC):
    """
    存储后端抽象基类。

    所有存储实现（本地/远程）必须提供完整文件操作能力。
    业务代码直接调用此接口，不再区分本地或远程。
    """

    def __init__(self, config: StorageConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        """后端唯一标识（来自配置 ID）"""
        return str(getattr(self.config, "id", ""))

    # ---------- 路径与元信息 ----------

    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在。"""

    @abstractmethod
    def stat(self, path: str) -> FileInfo | None:
        """获取文件元信息。"""

    @abstractmethod
    def list_dir(self, path: str) -> Iterator[FileInfo]:
        """列出目录内容。"""

    @abstractmethod
    def mkdir(self, path: str, parents: bool = True) -> None:
        """创建目录。"""

    @abstractmethod
    def remove(self, path: str, recursive: bool = False) -> None:
        """删除文件或目录。"""

    # ---------- 读写 ----------

    @abstractmethod
    def read_stream(self, path: str) -> BinaryIO:
        """获取读取流，调用方负责 close。"""

    @abstractmethod
    def write_stream(self, path: str, stream: BinaryIO, size: int = 0, chunk_size: int = 0) -> None:
        """从流写入，自动创建父目录。chunk_size 为 0 时由后端自行决定分块大小。"""

    # ---------- 同后端操作 ----------

    @abstractmethod
    def copy(self, src: str, dst: str) -> None:
        """同后端复制，尽可能使用服务端 COPY。"""

    @abstractmethod
    def move(self, src: str, dst: str) -> None:
        """同后端移动，尽可能使用服务端 MOVE。"""

    # ---------- 跨后端辅助 ----------

    def can_fast_cross_copy(self, other: "StorageBackend") -> bool:
        """是否支持向 another backend 做服务端快速复制。"""
        return False

    def cross_copy_to(self, src_path: str, dst_backend: "StorageBackend", dst_path: str) -> None:
        """向另一个后端执行服务端 COPY（如果支持）。"""
        raise NotImplementedError

    def health_check(self) -> tuple[bool, str]:
        """检查后端连接是否可用，返回 (是否成功, 消息)。"""
        return True, "ok"
