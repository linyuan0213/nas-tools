"""转移任务实体 — 统一目录同步与下载器转移的输入参数。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from app.core.exceptions import ValidationError


class SourceType(Enum):
    """转移来源类型。"""

    DIRECTORY = "directory"
    DOWNLOADER = "downloader"
    MANUAL = "manual"


_VALID_OPERATIONS = {"copy", "move", "link", "softlink", "rclone_copy", "rclone_move"}


@dataclass
class TransferTask:
    """
    统一转移任务。

    无论是目录同步、下载器完成转移还是手动触发，
    最终都封装为 TransferTask 提交给 TransferPipeline 执行。
    """

    source_type: SourceType
    """来源类型：directory / downloader / manual"""

    source_id: str = ""
    """来源标识：同步配置ID / 下载器ID / 空"""

    file_paths: list[str] = field(default_factory=list)
    """待处理的文件/目录路径列表"""

    operation: str = "copy"
    """转移方式：copy / move / link / softlink"""

    target_dir: str | None = None
    """目标目录（覆盖媒体库默认路径）"""

    unknown_dir: str | None = None
    """未识别文件存放目录"""

    dst_backend_id: str = "local"
    """目标存储后端 ID"""

    tmdb_info: dict[str, Any] | None = None
    """预知的 TMDB 信息（下载器场景可用）"""

    media_type: str | None = None
    """预知的媒体类型"""

    season: int | None = None
    """季号"""

    episode: tuple | None = None
    """集号信息"""

    fallback_episode: int | None = None
    """集号兜底（订阅/下载历史已知集号）：文件名解析不出集号时用于补齐 begin_episode"""

    post_process: Callable[["TransferTask", bool, str], None] | None = None
    """后处理回调：func(task, success, message) -> None"""

    def __post_init__(self):
        if isinstance(self.source_type, str):
            self.source_type = SourceType(self.source_type)

    @property
    def has_files(self) -> bool:
        """是否有待处理的文件"""
        return bool(self.file_paths)

    @property
    def is_valid_operation(self) -> bool:
        """转移方式是否有效"""
        return self.operation in _VALID_OPERATIONS

    def validate(self) -> None:
        """领域校验，失败时抛出 ValidationError"""
        if not self.has_files:
            raise ValidationError("没有待处理的文件")
        if not self.is_valid_operation:
            raise ValidationError(f"无效的转移方式：{self.operation}")
        if self.season is not None and (not isinstance(self.season, int) or self.season < 0):
            raise ValidationError(f"无效的季号：{self.season}")
