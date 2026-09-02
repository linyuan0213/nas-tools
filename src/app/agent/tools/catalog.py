"""工具目录 — Schema 与 handler 的显式映射（单一事实源，无注册副作用）

新增工具 = 在 schemas/ 定义类 + 在 handlers/ 写函数 + 在此登记两行。
"""

from collections.abc import Callable

from app.agent.tools.base import BaseTool
from app.agent.tools.handlers.browser import browser_fetch, browser_screenshot
from app.agent.tools.handlers.brush import brush_status
from app.agent.tools.handlers.config import config_get, config_set
from app.agent.tools.handlers.config_manifest import config_apply_manifest
from app.agent.tools.handlers.download import (
    download_add_link,
    download_control,
    download_history_list,
    download_list,
    downloader_status,
    media_download,
)
from app.agent.tools.handlers.downloader import downloader_config_get, downloader_config_save
from app.agent.tools.handlers.indexer import indexer_config_get, indexer_config_save
from app.agent.tools.handlers.library_sync import (
    media_library_dir_add,
    media_library_dir_remove,
    media_library_dirs_get,
    storage_backend_list,
    sync_path_list,
    sync_path_save,
)
from app.agent.tools.handlers.logs import system_logs
from app.agent.tools.handlers.media import kb_search, media_detail, media_search
from app.agent.tools.handlers.mediaserver import mediaserver_config_save, mediaserver_list
from app.agent.tools.handlers.message import (
    message_channel_types,
    message_client_delete,
    message_client_list,
    message_client_save,
)
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
from app.agent.tools.handlers.plugins import (
    plugin_config_save,
    plugin_disable,
    plugin_enable,
    plugin_info,
    plugin_list,
    plugin_run,
)
from app.agent.tools.handlers.rss_task import rss_task_list
from app.agent.tools.handlers.scraper import scraper_config_get, scraper_config_save
from app.agent.tools.handlers.search import web_search
from app.agent.tools.handlers.site import site_status, site_update_cookie
from app.agent.tools.handlers.subscribe import subscribe_add, subscribe_delete, subscribe_detail, subscribe_list
from app.agent.tools.handlers.words import words_add, words_delete, words_list, words_toggle
from app.agent.tools.schemas.browser import BrowserFetchTool, BrowserScreenshotTool
from app.agent.tools.schemas.brush import BrushStatusTool
from app.agent.tools.schemas.config import ConfigGetTool, ConfigSetTool
from app.agent.tools.schemas.config_manifest import ConfigApplyManifestTool
from app.agent.tools.schemas.download import (
    DownloadAddLinkTool,
    DownloadControlTool,
    DownloaderStatusTool,
    DownloadHistoryListTool,
    DownloadListTool,
    MediaDownloadTool,
)
from app.agent.tools.schemas.downloader import DownloaderConfigGetTool, DownloaderConfigSaveTool
from app.agent.tools.schemas.indexer import IndexerConfigGetTool, IndexerConfigSaveTool
from app.agent.tools.schemas.library_sync import (
    MediaLibraryDirAddTool,
    MediaLibraryDirRemoveTool,
    MediaLibraryDirsGetTool,
    StorageBackendListTool,
    SyncPathListTool,
    SyncPathSaveTool,
)
from app.agent.tools.schemas.logs import SystemLogsTool
from app.agent.tools.schemas.media import KbSearchTool, MediaDetailTool, MediaSearchTool
from app.agent.tools.schemas.mediaserver import MediaserverConfigSaveTool, MediaserverListTool
from app.agent.tools.schemas.message import (
    MessageChannelTypesTool,
    MessageClientDeleteTool,
    MessageClientListTool,
    MessageClientSaveTool,
)
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
from app.agent.tools.schemas.plugins import (
    PluginConfigSaveTool,
    PluginDisableTool,
    PluginEnableTool,
    PluginInfoTool,
    PluginListTool,
    PluginRunTool,
)
from app.agent.tools.schemas.rss_task import RssTaskListTool
from app.agent.tools.schemas.scraper import ScraperConfigGetTool, ScraperConfigSaveTool
from app.agent.tools.schemas.search import WebSearchTool
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
    WebSearchTool(),
    DownloadAddLinkTool(),
    MediaDownloadTool(),
    DownloadListTool(),
    DownloadControlTool(),
    DownloaderStatusTool(),
    DownloadHistoryListTool(),
    DownloaderConfigGetTool(),
    DownloaderConfigSaveTool(),
    PluginListTool(),
    PluginInfoTool(),
    PluginRunTool(),
    PluginEnableTool(),
    PluginDisableTool(),
    PluginConfigSaveTool(),
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
    MediaLibraryDirsGetTool(),
    MediaLibraryDirAddTool(),
    MediaLibraryDirRemoveTool(),
    StorageBackendListTool(),
    SyncPathListTool(),
    SyncPathSaveTool(),
    MediaserverListTool(),
    MediaserverConfigSaveTool(),
    SiteStatusTool(),
    SiteUpdateCookieTool(),
    IndexerConfigGetTool(),
    IndexerConfigSaveTool(),
    ScraperConfigGetTool(),
    ScraperConfigSaveTool(),
    BrushStatusTool(),
    TransferHistoryTool(),
    RssTaskListTool(),
    KbStatusTool(),
    IndexerStatusTool(),
    TorrentRemoverStatusTool(),
    StorageStatusTool(),
    ConfigGetTool(),
    ConfigSetTool(),
    ConfigApplyManifestTool(),
    MessageClientListTool(),
    MessageChannelTypesTool(),
    MessageClientSaveTool(),
    MessageClientDeleteTool(),
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
    "web_search": web_search,
    "download_add_link": download_add_link,
    "media_download": media_download,
    "download_list": download_list,
    "download_control": download_control,
    "downloader_status": downloader_status,
    "downloader_config_get": downloader_config_get,
    "downloader_config_save": downloader_config_save,
    "download_history_list": download_history_list,
    "plugin_list": plugin_list,
    "plugin_info": plugin_info,
    "plugin_run": plugin_run,
    "plugin_enable": plugin_enable,
    "plugin_disable": plugin_disable,
    "plugin_config_save": plugin_config_save,
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
    "media_library_dirs_get": media_library_dirs_get,
    "media_library_dir_add": media_library_dir_add,
    "media_library_dir_remove": media_library_dir_remove,
    "storage_backend_list": storage_backend_list,
    "sync_path_list": sync_path_list,
    "sync_path_save": sync_path_save,
    "mediaserver_list": mediaserver_list,
    "mediaserver_config_save": mediaserver_config_save,
    "site_status": site_status,
    "site_update_cookie": site_update_cookie,
    "indexer_config_get": indexer_config_get,
    "indexer_config_save": indexer_config_save,
    "scraper_config_get": scraper_config_get,
    "scraper_config_save": scraper_config_save,
    "brush_status": brush_status,
    "transfer_history": transfer_history,
    "rss_task_list": rss_task_list,
    "kb_status": kb_status,
    "indexer_status": indexer_status,
    "torrent_remover_status": torrent_remover_status,
    "storage_status": storage_status,
    "config_get": config_get,
    "config_set": config_set,
    "config_apply_manifest": config_apply_manifest,
    "message_client_list": message_client_list,
    "message_channel_types": message_channel_types,
    "message_client_save": message_client_save,
    "message_client_delete": message_client_delete,
    "words_list": words_list,
    "words_add": words_add,
    "words_toggle": words_toggle,
    "words_delete": words_delete,
    "memory_clear": memory_clear,
    "memory_forget": memory_forget,
}
