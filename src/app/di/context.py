"""应用运行时上下文 — 不可变对象图.

由 Builder 在 lifespan 中创建后挂到 app.state.context，
作为路由层获取依赖的唯一入口。

出于避免循环导入和减少维护成本的考虑，非核心 Service 字段使用 Any，
具体类型由各 Service 类自身保证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    from app.services.scheduler.core import SchedulerCore
    from app.services.system.lifecycle import SystemLifecycleService
    from app.sites.engine import SiteEngine
    from app.sites.site_cache import SiteCache


@dataclass(frozen=True)
class AppContext:
    """不可变应用上下文 — 运行时对象图的唯一持有者。"""

    # 基础设施层（强类型）
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
    media_server: MediaServer
    apikey_service: APIKeyService

    # 业务 Facade（强类型）
    media_service: MediaService
    tmdb_client: Any

    # Agent
    agent_service: Any
    media_recognizer: Any
    search_intent_agent: Any
    tool_executor: Any

    # 业务 Service（Any 避免循环导入和维护 80+ 类型）
    downloader_core: Any
    download_monitor: Any
    filetransfer_service: Any
    transfer_pipeline: Any
    sync_engine: Any
    sync_service: Any
    file_index_service: Any
    indexer_service: Any
    subscribe_service: Any
    searcher: Any
    rss_task_service: Any
    filter_service: Any
    torrent_remover_service: Any
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

    # 系统 Service
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

    # 协调器层
    subscription_monitor: Any
    system_lifecycle: SystemLifecycleService

    # 媒体身份解析（ADR-014）
    alias_index: AliasIndex
    edition_graph: EditionGraph
    identity_resolver: IdentityResolver
    target_matcher: TargetMatcher
    identity_builder: IdentityIndexBuilder
    episode_remapper: EpisodeRemapper

    # Agent RAG（未启用时为 None，带默认值便于最小构造）
    embedding_service: Any = None
    vector_store: Any = None
    retriever: Any = None
    knowledge_ingestor: Any = None
    conversation_store: Any = None
    semantic_memory: Any = None
