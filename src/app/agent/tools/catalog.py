"""工具目录 — Schema 与 handler 的显式映射（单一事实源，无注册副作用）

新增工具 = 在 schemas/ 定义类 + 在 handlers/ 写函数 + 在此登记两行。
"""

from collections.abc import Callable

from app.agent.tools.base import BaseTool
from app.agent.tools.handlers.browser import browser_fetch, browser_screenshot
from app.agent.tools.handlers.brush import brush_status
from app.agent.tools.handlers.download import (
    download_add_link,
    download_control,
    download_history_list,
    download_list,
    downloader_status,
    media_download,
)
from app.agent.tools.handlers.logs import system_logs
from app.agent.tools.handlers.media import kb_search, media_detail, media_search
from app.agent.tools.handlers.ops import (
    indexer_status,
    kb_status,
    library_check,
    memory_clear,
    memory_forget,
    scheduler_list,
    scheduler_run,
    stats_summary,
    storage_status,
    system_status,
    torrent_remover_status,
    transfer_history,
    transfer_run,
)
from app.agent.tools.handlers.plugins import plugin_info, plugin_list, plugin_run
from app.agent.tools.handlers.rss_task import rss_task_list
from app.agent.tools.handlers.site import site_status, site_update_cookie
from app.agent.tools.handlers.subscribe import subscribe_add, subscribe_delete, subscribe_detail, subscribe_list
from app.agent.tools.handlers.words import words_add, words_delete, words_list, words_toggle
from app.agent.tools.schemas.browser import BrowserFetchTool, BrowserScreenshotTool
from app.agent.tools.schemas.brush import BrushStatusTool
from app.agent.tools.schemas.download import (
    DownloadAddLinkTool,
    DownloadControlTool,
    DownloaderStatusTool,
    DownloadHistoryListTool,
    DownloadListTool,
    MediaDownloadTool,
)
from app.agent.tools.schemas.logs import SystemLogsTool
from app.agent.tools.schemas.media import KbSearchTool, MediaDetailTool, MediaSearchTool
from app.agent.tools.schemas.ops import (
    IndexerStatusTool,
    KbStatusTool,
    LibraryCheckTool,
    MemoryClearTool,
    MemoryForgetTool,
    SchedulerListTool,
    SchedulerRunTool,
    SiteUpdateCookieTool,
    StatsSummaryTool,
    StorageStatusTool,
    SystemStatusTool,
    TorrentRemoverStatusTool,
    TransferHistoryTool,
    TransferRunTool,
)
from app.agent.tools.schemas.plugins import PluginInfoTool, PluginListTool, PluginRunTool
from app.agent.tools.schemas.rss_task import RssTaskListTool
from app.agent.tools.schemas.site import SiteStatusTool
from app.agent.tools.schemas.subscribe import (
    SubscribeAddTool,
    SubscribeDeleteTool,
    SubscribeDetailTool,
    SubscribeListTool,
)
from app.agent.tools.schemas.words import WordsAddTool, WordsDeleteTool, WordsListTool, WordsToggleTool

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
    DownloadHistoryListTool(),
    PluginListTool(),
    PluginInfoTool(),
    PluginRunTool(),
    SubscribeAddTool(),
    SubscribeListTool(),
    SubscribeDetailTool(),
    SubscribeDeleteTool(),
    LibraryCheckTool(),
    TransferRunTool(),
    SchedulerListTool(),
    SchedulerRunTool(),
    SystemStatusTool(),
    StatsSummaryTool(),
    SystemLogsTool(),
    SiteStatusTool(),
    SiteUpdateCookieTool(),
    BrushStatusTool(),
    TransferHistoryTool(),
    RssTaskListTool(),
    KbStatusTool(),
    IndexerStatusTool(),
    TorrentRemoverStatusTool(),
    StorageStatusTool(),
    WordsListTool(),
    WordsAddTool(),
    WordsToggleTool(),
    WordsDeleteTool(),
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
    "download_history_list": download_history_list,
    "plugin_list": plugin_list,
    "plugin_info": plugin_info,
    "plugin_run": plugin_run,
    "subscribe_add": subscribe_add,
    "subscribe_list": subscribe_list,
    "subscribe_detail": subscribe_detail,
    "subscribe_delete": subscribe_delete,
    "library_check": library_check,
    "transfer_run": transfer_run,
    "scheduler_list": scheduler_list,
    "scheduler_run": scheduler_run,
    "system_status": system_status,
    "stats_summary": stats_summary,
    "system_logs": system_logs,
    "site_status": site_status,
    "site_update_cookie": site_update_cookie,
    "brush_status": brush_status,
    "transfer_history": transfer_history,
    "rss_task_list": rss_task_list,
    "kb_status": kb_status,
    "indexer_status": indexer_status,
    "torrent_remover_status": torrent_remover_status,
    "storage_status": storage_status,
    "words_list": words_list,
    "words_add": words_add,
    "words_toggle": words_toggle,
    "words_delete": words_delete,
    "memory_clear": memory_clear,
    "memory_forget": memory_forget,
}
