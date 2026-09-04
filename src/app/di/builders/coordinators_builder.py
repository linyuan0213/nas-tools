"""协调器 Builder — 创建 Layer 5 对象。"""

from app.agent.tool_executor import ToolExecutor
from app.agent.tools.context import ToolContext
from app.core.system_config import SystemConfig
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.db.repositories.subscribe_repo_adapter import SubscribeHistoryRepositoryAdapter
from app.di.builders.agent_builder import AgentRagObjects
from app.di.models import BusinessFacades, CoordinatorObjects, InfrastructureObjects, ServiceObjects
from app.media import MediaCache
from app.message.agent_enhancer import AgentMessageEnhancer
from app.services.rss_processor import RssHelper
from app.services.subscribe.coordinator import DownloadCoordinator
from app.services.subscribe.handlers import (
    build_rss_auto_subscribe_handler,
    build_subscribe_add_search_handler,
)
from app.services.subscribe.matcher import SubscribeMatcher
from app.services.subscribe.monitor import SubscriptionMonitor
from app.services.subscribe.strategies.indexer_search import IndexerSearchStrategy
from app.services.subscribe.strategies.queue_search import QueueSearchStrategy
from app.services.subscribe.strategies.rss_feed import RssFeedStrategy
from app.services.system.config import SystemConfigService
from app.services.system.lifecycle import SystemLifecycleService
from app.services.transfer.kb_ingest_handler import register_kb_ingest_handler
from app.sites import SiteConf


def build_coordinators(
    infra: InfrastructureObjects,
    facades: BusinessFacades,
    services: ServiceObjects,
    agent_rag: AgentRagObjects,
) -> CoordinatorObjects:
    """创建 Layer 5 协调器。"""
    downloader_core = services.downloader_core
    download_monitor = facades.download_monitor
    file_index_service = services.file_index_service
    media_server = facades.media_server
    rss_task_service = services.rss_task_service
    scheduler_core = infra.scheduler_core
    site_userinfo = services.site_service.site_user_info
    subscribe_service = services.subscribe_service
    sync_engine = services.sync_engine
    thread_executor = infra.thread_executor
    torrent_remover = services.torrent_remover_service
    searcher = services.searcher
    media_service = facades.media_service
    filter_service = services.filter_service
    site_cache = infra.site_cache
    site_engine = infra.site_engine
    message = infra.message

    siteconf = SiteConf(site_engine=site_engine)

    download_repo = DownloadHistoryRepositoryAdapter()
    rss_repo = SubscribeHistoryRepositoryAdapter()
    media_cache = MediaCache()
    system_config = SystemConfigService()

    matcher = SubscribeMatcher(site_conf=siteconf, site_cache=site_cache)
    queue_strategy = QueueSearchStrategy(
        service=subscribe_service,
        searcher=searcher,
        media_service=media_service,
        media_cache=media_cache,
        downloader=downloader_core,
        filter_service=filter_service,
        message=message,
        system_config=system_config,
    )
    rsshelper = RssHelper(site_engine=site_engine)
    rss_strategy = RssFeedStrategy(
        media=media_service,
        downloader=downloader_core,
        sites=site_cache,
        siteconf=siteconf,
        download_repo=download_repo,
        rss_repo=rss_repo,
        rsshelper=rsshelper,
        subscribe=subscribe_service,
        matcher=matcher,
        message=message,
        system_config=system_config,
    )
    indexer_strategy = IndexerSearchStrategy(
        service=subscribe_service,
        searcher=searcher,
        media_service=media_service,
        media_cache=media_cache,
        downloader=downloader_core,
        filter_service=filter_service,
        message=message,
        system_config=system_config,
    )
    subscription_monitor = SubscriptionMonitor(
        subscribe_service=subscribe_service,
        thread_executor=thread_executor,
        queue_strategy=queue_strategy,
        rss_strategy=rss_strategy,
        indexer_strategy=indexer_strategy,
        coordinator=DownloadCoordinator(),
        system_config=SystemConfig(),
    )

    system_lifecycle = SystemLifecycleService(
        scheduler_core=scheduler_core,
        download_monitor=download_monitor,
        sync=sync_engine,
        brush_task_service=services.brush_task_service,
        rss_checker=rss_task_service,
        torrent_remover=torrent_remover,
        downloader=downloader_core,
        file_index_service=file_index_service,
        subscription_monitor=subscription_monitor,
        site_userinfo=site_userinfo,
        subscribe_service=subscribe_service,
        media_server=media_server,
        thread_executor=thread_executor,
        hook_system=infra.hook_system,
        event_bus=infra.event_bus,
        knowledge_ingestor=agent_rag.knowledge_ingestor,
        conversation_store=agent_rag.conversation_store,
        plugin_market_service=services.plugin_market_service,
    )

    # RAG 知识库自动更新：媒体转移完成后节流重建 media_library 命名空间
    register_kb_ingest_handler(
        event_bus=infra.event_bus,
        knowledge_ingestor=agent_rag.knowledge_ingestor,
        thread_executor=thread_executor,
    )

    # 工具层：ToolContext 类型化注入 + 显式初始化 ChatAgent（替代旧 23 参数构造与 set_tool_executor 后门）
    tool_context = ToolContext(
        search_orchestrator=services.search_orchestrator,
        searcher=searcher,
        download_service=services.download_service,
        downloader_core=downloader_core,
        subscribe_service=subscribe_service,
        media_service=media_service,
        media_info_service=services.media_info_service,
        filetransfer_service=services.filetransfer_service,
        scheduler_service=services.scheduler_service,
        system_info_service=services.system_info_service,
        event_bus=infra.event_bus,
        site_service=services.site_service,
        brush_service=services.brush_service,
        media_library_service=services.media_library_service,
        transfer_history_service=services.transfer_history_service,
        user_rss_service=services.user_rss_service,
        knowledge_ingestor=agent_rag.knowledge_ingestor,
        indexer_service=services.indexer_service,
        torrent_remover_service=services.torrent_remover_service,
        storage_backend_service=services.storage_backend_service,
        words_service=services.words_service,
        plugin_framework_service=services.plugin_framework_service,
        message_client_service=services.message_client_service,
        media_server_config_service=services.media_server_config_service,
        indexer_config_service=services.indexer_config_service,
        system_config_service=services.system_config_service,
        media_config_service=services.media_config_service,
        sync_service=services.sync_service,
        retriever=agent_rag.retriever,
        conversation_store=agent_rag.conversation_store,
        semantic_memory=agent_rag.semantic_memory,
    )
    tool_executor = ToolExecutor(
        ctx=tool_context,
        plugin_tools_provider=(
            (lambda: services.plugin_framework_service.list_enabled_agent_tools())
            if services.plugin_framework_service
            else None
        ),
        plugin_executor=(
            (lambda plugin_id, name, args: services.plugin_framework_service.call_agent_tool(plugin_id, name, args))
            if services.plugin_framework_service
            else None
        ),
    )
    facades.agent_service.init_chat_agent(tool_executor, agent_rag.conversation_store, agent_rag.semantic_memory)

    # Agent 通知增强（单流替换模板通知，agent 未启用时零开销）
    if facades.agent_service.ready:
        infra.message.set_agent_enhancer(AgentMessageEnhancer(facades.agent_service))

    # 注册 RSS 自动订阅事件处理器
    build_rss_auto_subscribe_handler(subscribe_service)
    # 注册订阅添加/更新后自动触发队列搜索的事件处理器
    build_subscribe_add_search_handler(queue_strategy, thread_executor)

    return CoordinatorObjects(
        subscription_monitor=subscription_monitor,
        system_lifecycle=system_lifecycle,
        tool_executor=tool_executor,
    )
