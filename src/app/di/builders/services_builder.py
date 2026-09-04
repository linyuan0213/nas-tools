"""业务 Service Builder — 创建 Layer 4 对象。"""

from app import utils as string_utils_module
from app.core.system_config import SystemConfig
from app.db.repositories.brush_repo_adapter import BrushRuleRepositoryAdapter, BrushTaskRepositoryAdapter
from app.db.repositories.config_repo_adapter import (
    DownloaderRepositoryAdapter,
    FilterGroupRepositoryAdapter,
    FilterRuleRepositoryAdapter,
    MediaConfigRepositoryAdapter,
    MediaServerRepositoryAdapter,
    TorrentRemoveTaskRepositoryAdapter,
    UserRssConfigRepositoryAdapter,
)
from app.db.repositories.download_repo_adapter import (
    DownloadHistoryRepositoryAdapter,
    DownloadSettingRepositoryAdapter,
    IndexerStatisticsRepositoryAdapter,
)
from app.db.repositories.plugin_framework_repository import PluginFrameworkRepository
from app.db.repositories.plugin_market_repository import PluginMarketRepository
from app.db.repositories.rbac_repo_adapter import RBACMenuRepositoryAdapter, RBACRoleRepositoryAdapter
from app.db.repositories.search_repo_adapter import SearchRepositoryAdapter
from app.db.repositories.site_repo_adapter import SiteRepositoryAdapter
from app.db.repositories.site_repository import SiteRepository
from app.db.repositories.storage_backend_repo_adapter import StorageBackendRepositoryAdapter
from app.db.repositories.subscribe_repo_adapter import (
    SubscribeHistoryRepositoryAdapter,
    SubscribeMovieRepositoryAdapter,
    SubscribeTvEpisodeRepositoryAdapter,
    SubscribeTvRepositoryAdapter,
)
from app.db.repositories.sync_repo_adapter import SyncPathRepositoryAdapter
from app.db.repositories.transfer_repo_adapter import TransferBlacklistRepositoryAdapter
from app.db.repositories.word_repo_adapter import CustomWordGroupRepositoryAdapter, CustomWordRepositoryAdapter
from app.di.models import BusinessFacades, InfrastructureObjects, ServiceObjects
from app.domain.mediatypes import MediaType
from app.downloader.client_factory import DownloadClientFactory
from app.indexer.core.pipeline import SearchPipeline
from app.indexer.indexer import Indexer
from app.infrastructure.image_proxy import ImageProxy
from app.infrastructure.progress.tracker import ProgressTracker
from app.media import MediaCache
from app.media.external.bangumi import Bangumi
from app.media.external.douban import DouBan
from app.media.parser._release_groups import ReleaseGroupsMatcher
from app.media.scraper import Scraper
from app.services.brush.scheduler import BrushTaskScheduler
from app.services.brush.task_service import BrushTaskService
from app.services.brush_service import BrushService
from app.services.config_service import ConfigService
from app.services.download_core import DownloadCore
from app.services.download_service import DownloadService
from app.services.downloader_core import DownloaderCore
from app.services.file_index_service import FileIndexService
from app.services.filter_service import FilterService
from app.services.indexer_service import IndexerService
from app.services.media_config_service import MediaConfigService
from app.services.media_file_service import MediaFileService
from app.services.media_info_service import MediaInfoService
from app.services.media_library_service import MediaLibraryService
from app.services.media_recommendation_service import MediaRecommendationService
from app.services.plugin_framework_service import PluginFrameworkService
from app.services.plugin_market_service import PluginMarketService
from app.services.rbac.service import RBACService
from app.services.rss_automation.task_service import RssTaskService
from app.services.rss_automation.userrss_service import UserRssService
from app.services.rss_processor import RssHelper
from app.services.scheduler_service import SchedulerService
from app.services.scrape_queue_service import ScrapeQueueService
from app.services.search_intent_resolver import IntentResolverChain
from app.services.search_orchestrator import SearchOrchestrator
from app.services.search_result_service import SearchResultService
from app.services.search_service import Searcher
from app.services.search_web_entry import make_web_search_fn
from app.services.site_service import SiteService
from app.services.storage_backend_service import StorageBackendService
from app.services.subscribe.management.calendar_service import SubscribeCalendarService
from app.services.subscribe.management.history_service import SubscribeHistoryService
from app.services.subscribe_service import SubscribeService
from app.services.sync_engine import SyncEngine
from app.services.sync_service import SyncService
from app.services.system.backup import BackupRestoreService
from app.services.system.config import IndexerConfigService, MediaServerConfigService, SystemConfigService
from app.services.system.info import (
    NetTestService,
    ProgressService,
    SystemInfoService,
    UserManageService,
    WebSearchService,
)
from app.services.system.message import MessageClientService, MessageSenderService
from app.services.tmdb_blacklist_service import TmdbBlacklistService
from app.services.torrentremover_core import TorrentRemoverRepository, TorrentRemoverService
from app.services.transfer.cleanup_service import TransferCleanupService
from app.services.transfer.existence_checker import MediaExistenceChecker
from app.services.transfer.filetransfer_service import FileTransferService
from app.services.transfer.handlers import register_download_completed_handler
from app.services.transfer.history_manager import TransferHistoryManager
from app.services.transfer.path_resolver import TransferPathResolver
from app.services.transfer_coordinator import TransferCoordinator
from app.services.transfer_engine import TransferEngine
from app.services.transfer_history_service import TransferHistoryService
from app.services.transfer_pipeline import TransferPipeline
from app.services.words_service import WordsService
from app.sites import SiteConf, SiteSubtitle
from app.sites.site_cookie import SiteCookie
from app.sites.site_favicon_service import SiteFaviconService
from app.sites.site_resolver import SiteResolver
from app.sites.site_userinfo import SiteUserInfo


def build_services(infra: InfrastructureObjects, facades: BusinessFacades) -> ServiceObjects:
    """创建 Layer 4 业务 Service。"""
    event_bus = infra.event_bus
    media_server = facades.media_server
    media_service = facades.media_service
    message = infra.message
    site_cache = infra.site_cache
    site_engine = infra.site_engine
    thread_executor = infra.thread_executor
    scheduler_core = infra.scheduler_core
    indexer_site_config_repo = infra.indexer_site_config_repo

    siteconf = SiteConf(site_engine=site_engine)
    sitesubtitle = SiteSubtitle(siteconf=siteconf, sites=site_cache, site_engine=site_engine)

    transfer_engine = TransferEngine()

    media_config_service = MediaConfigService(repo=MediaConfigRepositoryAdapter())

    path_resolver = TransferPathResolver.from_settings(media_config_service=media_config_service)
    existence_checker = MediaExistenceChecker(
        path_resolver=path_resolver,
        media_service=media_service,
    )
    history_manager = TransferHistoryManager()
    cleanup_service = TransferCleanupService(
        history_manager=history_manager,
        path_resolver=path_resolver,
        media_service=media_service,
        message=message,
        event_bus=event_bus,
    )

    shared_scraper = Scraper(media_service=media_service)
    scrape_queue_service = ScrapeQueueService(scraper=shared_scraper)

    filetransfer_service = FileTransferService(
        media_service=media_service,
        message=message,
        scrape_queue_service=scrape_queue_service,
        thread_executor=thread_executor,
        history_manager=history_manager,
        progress=ProgressTracker(),
        event_bus=event_bus,
        engine=transfer_engine,
        sync_path_repo=SyncPathRepositoryAdapter(),
        path_resolver=path_resolver,
        existence_checker=existence_checker,
        cleanup_service=cleanup_service,
    )

    transfer_pipeline = TransferPipeline(
        filetransfer=filetransfer_service,
        scrape_queue_service=scrape_queue_service,
        blacklist_repo=TransferBlacklistRepositoryAdapter(),
        backend_repo=StorageBackendRepositoryAdapter(),
    )
    register_download_completed_handler(
        event_bus=event_bus,
        transfer_pipeline=transfer_pipeline,
        download_history_repo=DownloadHistoryRepositoryAdapter(),
        media_cache=MediaCache(),
    )

    shared_client_factory = DownloadClientFactory()

    download_core = DownloadCore(
        client_factory=shared_client_factory,
        message=message,
        mediaserver=media_server,
        filetransfer=filetransfer_service,
        sites=site_cache,
        siteconf=siteconf,
        sitesubtitle=sitesubtitle,
        event_bus=event_bus,
        download_repo=DownloadHistoryRepositoryAdapter(),
        download_setting_repo=DownloadSettingRepositoryAdapter(),
        systemconfig=SystemConfig(),
        downloader_repo=DownloaderRepositoryAdapter(),
        site_engine=site_engine,
        site_config_repo=indexer_site_config_repo,
    )

    downloader_core = DownloaderCore(
        client_factory=shared_client_factory,
        transfer_coordinator=TransferCoordinator(scheduler=scheduler_core),
        transfer_pipeline=transfer_pipeline,
        download_core=download_core,
        download_monitor=facades.download_monitor,
    )

    filter_service = FilterService(
        filter_group_repo=FilterGroupRepositoryAdapter(),
        filter_rule_repo=FilterRuleRepositoryAdapter(),
        rg_matcher=ReleaseGroupsMatcher(),
    )

    search_pipeline = SearchPipeline(media_service=media_service)

    indexer = Indexer(
        search_pipeline=search_pipeline,
        indexer_helper=infra.indexer_helper,
        site_cache=site_cache,
        site_engine=site_engine,
        site_config_repo=indexer_site_config_repo,
    )

    indexer_service = IndexerService(
        indexer=indexer,
        indexer_helper=infra.indexer_helper,
        site_cache=site_cache,
        site_engine=site_engine,
        indexer_statistics_repo=IndexerStatisticsRepositoryAdapter(),
        string_utils=string_utils_module,
        site_config_repo=indexer_site_config_repo,
    )

    subscribe_service = SubscribeService(
        movie_repo=SubscribeMovieRepositoryAdapter(),
        tv_repo=SubscribeTvRepositoryAdapter(),
        tv_episode_repo=SubscribeTvEpisodeRepositoryAdapter(),
        history_repo=SubscribeHistoryRepositoryAdapter(),
        message=message,
        media_service=media_service,
        downloader=downloader_core,
        sites=site_cache,
        douban=DouBan(),
        indexer_service=indexer_service,
        filter_service=filter_service,
        event_bus=event_bus,
        system_config=SystemConfig(),
        download_repo=DownloadHistoryRepositoryAdapter(),
        transfer_history_manager=history_manager,
    )

    searcher = Searcher(
        download_repo=DownloadHistoryRepositoryAdapter(),
        search_repo=SearchRepositoryAdapter(),
        downloader=downloader_core,
        media_service=media_service,
        message=message,
        progress_helper=ProgressTracker(),
        indexer_service=indexer_service,
        event_bus=event_bus,
    )

    sync_engine = SyncEngine(
        transfer_engine=transfer_engine,
        transfer_pipeline=transfer_pipeline,
        sync_path_repo=SyncPathRepositoryAdapter(),
        storage_backend_repo=StorageBackendRepositoryAdapter(),
        thread_executor=thread_executor,
        sync_workers=4,
    )

    sync_service = SyncService(
        sync=sync_engine,
        filetransfer=filetransfer_service,
        media_cache=MediaCache(),
        thread_executor=thread_executor,
        storage_backend_repo=StorageBackendRepositoryAdapter(),
    )

    file_index_service = FileIndexService(sync_path_repo=SyncPathRepositoryAdapter())

    torrent_remover = TorrentRemoverService(
        repository=TorrentRemoverRepository(config_repo=TorrentRemoveTaskRepositoryAdapter()),
        downloader=downloader_core,
        message=message,
        scheduler=scheduler_core,
    )

    rss_task_service = RssTaskService(
        config_repo=UserRssConfigRepositoryAdapter(),
        rss_repo=SubscribeHistoryRepositoryAdapter(),
        rsshelper=RssHelper(site_engine=site_engine),
        message=message,
        searcher=searcher,
        filter_=filter_service,
        media=media_service,
        downloader=downloader_core,
        scheduler_core=scheduler_core,
        site_engine=site_engine,
        event_bus=event_bus,
    )

    config_service = ConfigService()
    message_sender_service = MessageSenderService(message=message)
    system_info_service = SystemInfoService(message=message)
    net_test_service = NetTestService()
    progress_service = ProgressService()

    # 搜索/意图统一：规则+LLM 意图解析链 + 唯一搜索编排入口
    intent_resolver = IntentResolverChain(llm_resolver=facades.search_intent_agent)
    search_orchestrator = SearchOrchestrator(
        searcher=searcher,
        search_repo=SearchRepositoryAdapter(),
        download_repo=DownloadHistoryRepositoryAdapter(),
        downloader=downloader_core,
        media_service=media_service,
        message=message,
        progress_helper=ProgressTracker(),
        event_bus=event_bus,
        intent_resolver=intent_resolver,
    )
    web_search_service = WebSearchService(
        search_fn=make_web_search_fn(search_orchestrator, SystemConfigService()),
    )
    backup_restore_service = BackupRestoreService()
    rbac_service = RBACService()
    user_rss_service = UserRssService(rss_checker=rss_task_service)

    douban = DouBan()
    media_info_service = MediaInfoService(
        media_service=media_service,
        subscribe=subscribe_service,
        media_server=media_server,
        douban=douban,
    )

    download_service = DownloadService(
        downloader=downloader_core,
        searcher=searcher,
        media_service=media_service,
        sites=site_cache,
        site_engine=site_engine,
        indexer_service=indexer_service,
        torrent_remover=torrent_remover,
        download_history_repo=DownloadHistoryRepositoryAdapter(),
    )

    plugin_framework_service = PluginFrameworkService(
        repo=PluginFrameworkRepository(),
        menu_repo=RBACMenuRepositoryAdapter(),
        role_repo=RBACRoleRepositoryAdapter(),
        plugin_registry=infra.plugin_registry,
        plugin_sandbox=infra.plugin_sandbox,
        hook_system=infra.hook_system,
    )

    plugin_market_service = PluginMarketService(
        store=PluginMarketRepository(),
        plugin_installer=(
            (lambda data, enabled: plugin_framework_service.install_market_plugin(data, enabled=enabled))
            if plugin_framework_service
            else None
        ),
        plugin_updater=(
            (lambda data, plugin_id: plugin_framework_service.update_market_plugin(data, plugin_id))
            if plugin_framework_service
            else None
        ),
    )

    storage_backend_service = StorageBackendService(
        repo=StorageBackendRepositoryAdapter(),
    )

    scheduler_service = SchedulerService(scheduler_core=scheduler_core)

    tmdb_blacklist_service = TmdbBlacklistService(media_service=media_service)

    media_server_config_service = MediaServerConfigService(
        config_repo=MediaServerRepositoryAdapter(),
        media_server=media_server,
    )
    media_file_service = MediaFileService(
        event_bus=event_bus,
        storage_backend_repo=StorageBackendRepositoryAdapter(),
        media_service=media_service,
        thread_executor=thread_executor,
        scraper=Scraper(media_service=media_service),
    )
    media_library_service = MediaLibraryService(
        media_server=media_server,
        filetransfer=filetransfer_service,
        system_config=SystemConfig(),
        thread_executor=thread_executor,
        media_config_service=media_config_service,
    )
    media_recommendation_service = MediaRecommendationService(
        media_service=media_service,
        douban=douban,
        bangumi=Bangumi(),
        media_server=media_server,
        subscribe=subscribe_service,
        media_info_service=media_info_service,
        downloader_core=downloader_core,
    )

    system_config_service = SystemConfigService()
    indexer_config_service = IndexerConfigService(
        indexer_service=indexer_service,
        indexer=indexer_service.indexer,
        site_config_repo=indexer_site_config_repo,
    )
    user_manage_service = UserManageService(rbac_svc=rbac_service)
    message_client_service = MessageClientService(message=message)

    brush_task_service = BrushTaskService(
        repository=BrushTaskRepositoryAdapter(),
        scheduler=BrushTaskScheduler(scheduler=scheduler_core),
        downloader=downloader_core,
        message=message,
        sites=site_cache,
        siteconf=siteconf,
        site_engine=site_engine,
        rsshelper=RssHelper(site_engine=site_engine),
        filter_service=filter_service,
        brush_rule_repo=BrushRuleRepositoryAdapter(),
        media_service=media_service,
    )
    brush_service = BrushService(
        brush_task=brush_task_service,
        rule_repo=BrushRuleRepositoryAdapter(),
    )

    site_favicon_service = SiteFaviconService(
        cache=site_cache,
        site_engine=site_engine,
        repo=SiteRepository(),
    )
    site_userinfo = SiteUserInfo(
        site_cache=site_cache,
        site_repository=SiteRepository(),
        site_favicon_service=site_favicon_service,
        site_engine=site_engine,
        message=message,
        thread_executor=thread_executor,
    )
    site_resolver = SiteResolver(cache=site_cache, site_engine=site_engine)
    site_service = SiteService(
        sites=site_cache,
        site_user_info=site_userinfo,
        site_conf=siteconf,
        indexer_service=indexer_service,
        site_repo=SiteRepository(),
        site_favicon_service=site_favicon_service,
        site_resolver=site_resolver,
        site_cookie=SiteCookie(sites=site_cache, site_engine=site_engine),
        string_utils=string_utils_module,
        site_entity_repo=SiteRepositoryAdapter(),
        indexer_site_config_repo=indexer_site_config_repo,
        site_engine=site_engine,
    )

    # 需要在数据库初始化后构造的服务
    words_service = WordsService(
        media_cache=MediaCache(),
        word_repo=CustomWordRepositoryAdapter(),
        group_repo=CustomWordGroupRepositoryAdapter(),
    )
    subscribe_calendar_service = SubscribeCalendarService(
        media_info_service=media_info_service,
        subscribe=subscribe_service,
        rss_task_service=rss_task_service,
    )
    subscribe_history_service = SubscribeHistoryService(
        history_repo=SubscribeHistoryRepositoryAdapter(),
        subscribe=subscribe_service,
        rss_helper=RssHelper(site_engine=site_engine),
    )
    search_result_service = SearchResultService(
        media_server=media_server,
        subscribe=subscribe_service,
    )

    def _history_poster_resolver(type_value: str, tmdbid: int) -> str:
        """按 (类型, TMDBID) 解析海报 URL：优先缓存，缺失时回源一次并回填缓存."""
        try:
            mtype = MediaType.from_string(type_value)
            if mtype not in (MediaType.MOVIE, MediaType.TV, MediaType.ANIME) or not tmdbid:
                return ""
            info = MediaCache().get_tmdb_info(mtype, tmdbid)
            if not info:
                info = media_service.get_tmdb_info(mtype, str(tmdbid), chinese=True)  # type: ignore[union-attr]
            poster_path = (info or {}).get("poster_path") or ""
            return ImageProxy.get_tmdbimage_url(poster_path) if poster_path else ""
        except Exception:
            return ""

    transfer_history_service = TransferHistoryService(
        filetransfer=filetransfer_service,
        sync_service=sync_service,
        poster_resolver=_history_poster_resolver,
    )

    # 回填 PluginSandbox 的服务依赖（供动态加载插件使用）
    if infra.plugin_sandbox._searcher is None:
        infra.plugin_sandbox._searcher = searcher
    if infra.plugin_sandbox._downloader_core is None:
        infra.plugin_sandbox._downloader_core = downloader_core
    if infra.plugin_sandbox._subscribe_service is None:
        infra.plugin_sandbox._subscribe_service = subscribe_service
    if infra.plugin_sandbox._media_server is None:
        infra.plugin_sandbox._media_server = media_server
    if infra.plugin_sandbox._sync_engine is None:
        infra.plugin_sandbox._sync_engine = sync_engine
    if infra.plugin_sandbox._site_cache is None:
        infra.plugin_sandbox._site_cache = site_cache
    if infra.plugin_sandbox._filetransfer_service is None:
        infra.plugin_sandbox._filetransfer_service = filetransfer_service
    if infra.plugin_sandbox._site_resolver is None:
        infra.plugin_sandbox._site_resolver = site_resolver
    if infra.plugin_sandbox._site_service is None:
        infra.plugin_sandbox._site_service = site_service
    if infra.plugin_sandbox._event_bus is None:
        infra.plugin_sandbox._event_bus = infra.event_bus

    return ServiceObjects(
        downloader_core=downloader_core,
        filetransfer_service=filetransfer_service,
        transfer_pipeline=transfer_pipeline,
        sync_engine=sync_engine,
        sync_service=sync_service,
        file_index_service=file_index_service,
        indexer_service=indexer_service,
        subscribe_service=subscribe_service,
        searcher=searcher,
        rss_task_service=rss_task_service,
        filter_service=filter_service,
        torrent_remover_service=torrent_remover,
        brush_task_service=brush_task_service,
        brush_service=brush_service,
        site_service=site_service,
        site_resolver=site_resolver,
        site_favicon_service=site_favicon_service,
        media_info_service=media_info_service,
        media_config_service=media_config_service,
        media_file_service=media_file_service,
        media_library_service=media_library_service,
        media_recommendation_service=media_recommendation_service,
        media_server_config_service=media_server_config_service,
        system_config_service=system_config_service,
        indexer_config_service=indexer_config_service,
        rbac_service=rbac_service,
        config_service=config_service,
        message_sender_service=message_sender_service,
        message_client_service=message_client_service,
        scheduler_service=scheduler_service,
        system_info_service=system_info_service,
        net_test_service=net_test_service,
        progress_service=progress_service,
        web_search_service=web_search_service,
        search_orchestrator=search_orchestrator,
        backup_restore_service=backup_restore_service,
        user_manage_service=user_manage_service,
        tmdb_blacklist_service=tmdb_blacklist_service,
        download_service=download_service,
        plugin_framework_service=plugin_framework_service,
        plugin_market_service=plugin_market_service,
        storage_backend_service=storage_backend_service,
        search_result_service=search_result_service,
        transfer_history_service=transfer_history_service,
        subscribe_calendar_service=subscribe_calendar_service,
        subscribe_history_service=subscribe_history_service,
        words_service=words_service,
        user_rss_service=user_rss_service,
    )
