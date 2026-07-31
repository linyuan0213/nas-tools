"""协调器 Builder — 创建 Layer 5 对象。"""

from app.agent.tool_executor import ToolExecutor
from app.core.system_config import SystemConfig
from app.db.repositories.download_repo_adapter import DownloadHistoryRepositoryAdapter
from app.db.repositories.subscribe_repo_adapter import SubscribeHistoryRepositoryAdapter
from app.di.models import BusinessFacades, CoordinatorObjects, InfrastructureObjects, ServiceObjects
from app.media import MediaCache
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
from app.sites import SiteConf


def build_coordinators(
    infra: InfrastructureObjects,
    facades: BusinessFacades,
    services: ServiceObjects,
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

    matcher = SubscribeMatcher(site_conf=siteconf, site_cache=site_cache)
    queue_strategy = QueueSearchStrategy(
        service=subscribe_service,
        searcher=searcher,
        media_service=media_service,
        media_cache=media_cache,
        downloader=downloader_core,
        filter_service=filter_service,
        message=message,
        system_config=SystemConfigService(),
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
    )
    indexer_strategy = IndexerSearchStrategy(
        service=subscribe_service,
        searcher=searcher,
        media_service=media_service,
        media_cache=media_cache,
        downloader=downloader_core,
        filter_service=filter_service,
        message=message,
        system_config=SystemConfigService(),
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
    )

    # 创建 ToolExecutor 并注入 AgentService（解决循环依赖）
    tool_executor = ToolExecutor(
        message=message,
        thread_executor=thread_executor,
        scheduler_core=scheduler_core,
        event_bus=infra.event_bus,
        download_monitor=download_monitor,
        filetransfer_service=services.filetransfer_service,
        rss_helper=RssHelper(site_engine=site_engine),
        search_intent_agent=facades.search_intent_agent,
        site_userinfo=site_userinfo,
        scheduler_service=services.scheduler_service,
        message_client_service=services.message_client_service,
        sync_service=services.sync_service,
        subscription_monitor=subscription_monitor,
        torrentremover_service=torrent_remover,
        subscribe_service=subscribe_service,
        system_lifecycle_service=system_lifecycle,
        brush_service=services.brush_service,
        site_service=services.site_service,
        rss_task_service=rss_task_service,
        media_service=media_service,
        indexer_service=services.indexer_service,
        downloader_core=downloader_core,
        searcher=searcher,
    )
    facades.agent_service.set_tool_executor(tool_executor)

    # 注册 RSS 自动订阅事件处理器
    build_rss_auto_subscribe_handler(subscribe_service)
    # 注册订阅添加/更新后自动触发队列搜索的事件处理器
    build_subscribe_add_search_handler(queue_strategy, thread_executor)

    return CoordinatorObjects(
        subscription_monitor=subscription_monitor,
        system_lifecycle=system_lifecycle,
        tool_executor=tool_executor,
    )
