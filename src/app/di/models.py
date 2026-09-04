"""Builder 中间模型 — 按层分组对象，降低 AppContext 直接组装的复杂度。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
    from app.events.bus import EventBus
    from app.infrastructure.queue.base import MessageQueue
    from app.infrastructure.thread import ThreadExecutor
    from app.media.identity.builder import IdentityIndexBuilder
    from app.media.identity.graph import EditionGraph
    from app.media.identity.index import AliasIndex
    from app.media.identity.matcher import TargetMatcher
    from app.media.identity.remapper import EpisodeRemapper
    from app.media.identity.resolver import IdentityResolver
    from app.media.service import MediaService
    from app.mediaserver.media_server import MediaServer
    from app.message.message import Message
    from app.plugin_framework.hook_system import HookSystem
    from app.plugin_framework.registry import PluginRegistry
    from app.plugin_framework.sandbox import PluginSandbox
    from app.services.apikey_service import APIKeyService
    from app.services.download_monitor import DownloadMonitor
    from app.services.downloader_core import DownloaderCore
    from app.services.file_index_service import FileIndexService
    from app.services.filter_service import FilterService
    from app.services.indexer_service import IndexerService
    from app.services.rss_automation.task_service import RssTaskService
    from app.services.scheduler.core import SchedulerCore
    from app.services.search_service import Searcher
    from app.services.subscribe.monitor import SubscriptionMonitor
    from app.services.subscribe_service import SubscribeService
    from app.services.sync_engine import SyncEngine
    from app.services.sync_service import SyncService
    from app.services.system.lifecycle import SystemLifecycleService
    from app.services.torrentremover_core import TorrentRemoverService
    from app.services.transfer.filetransfer_service import FileTransferService
    from app.services.transfer_pipeline import TransferPipeline
    from app.sites.engine import SiteEngine
    from app.sites.site_cache import SiteCache


@dataclass(frozen=True)
class InfrastructureObjects:
    """Layer 1 基础设施对象。"""

    event_bus: EventBus
    thread_executor: ThreadExecutor
    scheduler_core: SchedulerCore
    message: Message
    message_queue: MessageQueue
    site_cache: SiteCache
    site_engine: SiteEngine
    hook_system: HookSystem
    plugin_sandbox: PluginSandbox
    plugin_registry: PluginRegistry
    apikey_service: APIKeyService
    indexer_site_config_repo: IndexerSiteConfigRepositoryAdapter
    indexer_helper: Any


@dataclass(frozen=True)
class BusinessFacades:
    """Layer 3 业务 Facade。"""

    media_service: MediaService
    media_server: MediaServer
    tmdb_client: Any
    agent_service: Any
    media_recognizer: Any
    search_intent_agent: Any
    download_monitor: DownloadMonitor


@dataclass(frozen=True)
class ServiceObjects:
    """Layer 4 业务 Service。"""

    downloader_core: DownloaderCore
    filetransfer_service: FileTransferService
    transfer_pipeline: TransferPipeline
    sync_engine: SyncEngine
    sync_service: SyncService
    file_index_service: FileIndexService
    indexer_service: IndexerService
    subscribe_service: SubscribeService
    searcher: Searcher
    rss_task_service: RssTaskService
    filter_service: FilterService
    torrent_remover_service: TorrentRemoverService
    brush_task_service: Any
    brush_service: Any
    site_service: Any
    site_resolver: Any
    site_favicon_service: Any
    media_info_service: Any
    media_config_service: Any
    media_file_service: Any
    media_library_service: Any
    media_recommendation_service: Any
    media_server_config_service: Any
    system_config_service: Any
    indexer_config_service: Any
    rbac_service: Any
    config_service: Any
    message_sender_service: Any
    message_client_service: Any
    scheduler_service: Any
    system_info_service: Any
    net_test_service: Any
    progress_service: Any
    web_search_service: Any
    search_orchestrator: Any
    backup_restore_service: Any
    user_manage_service: Any
    tmdb_blacklist_service: Any
    download_service: Any
    plugin_framework_service: Any
    plugin_market_service: Any
    storage_backend_service: Any
    search_result_service: Any
    transfer_history_service: Any
    subscribe_calendar_service: Any
    subscribe_history_service: Any
    words_service: Any
    user_rss_service: Any


@dataclass(frozen=True)
class CoordinatorObjects:
    """Layer 5 协调器。"""

    subscription_monitor: SubscriptionMonitor
    system_lifecycle: SystemLifecycleService
    tool_executor: Any


@dataclass(frozen=True)
class IdentityObjects:
    """ADR-014 媒体身份解析组件（共享 AliasIndex / EditionGraph 依赖）。"""

    alias_index: AliasIndex
    edition_graph: EditionGraph
    identity_resolver: IdentityResolver
    target_matcher: TargetMatcher
    identity_builder: IdentityIndexBuilder
    episode_remapper: EpisodeRemapper
