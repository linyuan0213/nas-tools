"""工具目录 — Schema 与 handler 的显式映射（单一事实源，无注册副作用）

新增工具 = 在 schemas/ 定义类 + 在 handlers/ 写函数 + 在此登记两行。
"""

from collections.abc import Callable

from app.agent.tools.base import BaseTool
from app.agent.tools.handlers.browser import browser_fetch, browser_screenshot
from app.agent.tools.handlers.download import (
    download_add_link,
    download_control,
    download_list,
    downloader_status,
    media_download,
)
from app.agent.tools.handlers.logs import system_logs
from app.agent.tools.handlers.media import kb_search, media_detail, media_search
from app.agent.tools.handlers.ops import (
    library_check,
    memory_clear,
    memory_forget,
    scheduler_list,
    scheduler_run,
    system_status,
    transfer_run,
)
from app.agent.tools.handlers.subscribe import subscribe_add, subscribe_delete, subscribe_list
from app.agent.tools.schemas.browser import BrowserFetchTool, BrowserScreenshotTool
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
    MemoryForgetTool,
    SchedulerListTool,
    SchedulerRunTool,
    SystemStatusTool,
    TransferRunTool,
)
from app.agent.tools.schemas.subscribe import SubscribeAddTool, SubscribeDeleteTool, SubscribeListTool

BUILTIN_TOOLS: list[BaseTool] = [
    MediaSearchTool(),
    MediaDetailTool(),
    KbSearchTool(),
    BrowserFetchTool(),
    BrowserScreenshotTool(),
    DownloadAddLinkTool(),
    MediaDownloadTool(),
    DownloadListTool(),
    DownloadControlTool(),
    DownloaderStatusTool(),
    SubscribeAddTool(),
    SubscribeListTool(),
    SubscribeDeleteTool(),
    LibraryCheckTool(),
    TransferRunTool(),
    SchedulerListTool(),
    SchedulerRunTool(),
    SystemStatusTool(),
    SystemLogsTool(),
    MemoryClearTool(),
    MemoryForgetTool(),
]

HANDLERS: dict[str, Callable] = {
    "media_search": media_search,
    "media_detail": media_detail,
    "kb_search": kb_search,
    "browser_fetch": browser_fetch,
    "browser_screenshot": browser_screenshot,
    "download_add_link": download_add_link,
    "media_download": media_download,
    "download_list": download_list,
    "download_control": download_control,
    "downloader_status": downloader_status,
    "subscribe_add": subscribe_add,
    "subscribe_list": subscribe_list,
    "subscribe_delete": subscribe_delete,
    "library_check": library_check,
    "transfer_run": transfer_run,
    "scheduler_list": scheduler_list,
    "scheduler_run": scheduler_run,
    "system_status": system_status,
    "system_logs": system_logs,
    "memory_clear": memory_clear,
    "memory_forget": memory_forget,
}
