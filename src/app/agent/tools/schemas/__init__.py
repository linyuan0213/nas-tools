"""工具 Schema 包 — 纯类定义导出（注册由 catalog 显式完成）"""

from app.agent.tools.schemas.download import (
    DownloadAddLinkTool,
    DownloadControlTool,
    DownloaderStatusTool,
    DownloadListTool,
    MediaDownloadTool,
)
from app.agent.tools.schemas.logs import SystemLogsTool
from app.agent.tools.schemas.media import KbSearchTool, MediaDetailTool, MediaSearchTool
from app.agent.tools.schemas.ops import (
    LibraryCheckTool,
    MemoryClearTool,
    SchedulerListTool,
    SchedulerRunTool,
    SystemStatusTool,
    TransferRunTool,
)
from app.agent.tools.schemas.subscribe import SubscribeAddTool, SubscribeDeleteTool, SubscribeListTool

__all__ = [
    "MediaSearchTool",
    "MediaDetailTool",
    "KbSearchTool",
    "DownloadAddLinkTool",
    "MediaDownloadTool",
    "DownloadListTool",
    "DownloadControlTool",
    "DownloaderStatusTool",
    "SubscribeAddTool",
    "SubscribeListTool",
    "SubscribeDeleteTool",
    "LibraryCheckTool",
    "TransferRunTool",
    "SchedulerListTool",
    "SchedulerRunTool",
    "SystemStatusTool",
    "SystemLogsTool",
    "MemoryClearTool",
]
