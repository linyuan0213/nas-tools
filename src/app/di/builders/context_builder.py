"""上下文 Builder — 组装完整 AppContext。"""

import log
from app.di.builders.agent_builder import build_agent_rag
from app.di.builders.coordinators_builder import build_coordinators
from app.di.builders.facades_builder import build_business_facades
from app.di.builders.identity_builder import build_identity
from app.di.builders.infrastructure_builder import build_infrastructure
from app.di.builders.services_builder import build_services
from app.di.context import AppContext


def build_app_context() -> AppContext:
    """按拓扑顺序组装整个应用对象图。"""
    log.info("[DI]开始构建对象图...")
    infra = build_infrastructure()
    facades = build_business_facades(infra)
    identity = build_identity(facades)
    services = build_services(infra, facades)
    agent_rag = build_agent_rag(facades.agent_service, services.media_library_service)
    coordinators = build_coordinators(infra, facades, services, agent_rag)

    context = AppContext(
        event_bus=infra.event_bus,
        thread_executor=infra.thread_executor,
        scheduler_core=infra.scheduler_core,
        message=infra.message,
        message_queue=infra.message_queue,
        site_cache=infra.site_cache,
        site_engine=infra.site_engine,
        hook_system=infra.hook_system,
        plugin_sandbox=infra.plugin_sandbox,
        plugin_registry=infra.plugin_registry,
        media_server=facades.media_server,
        apikey_service=infra.apikey_service,
        media_service=facades.media_service,
        tmdb_client=facades.tmdb_client,
        agent_service=facades.agent_service,
        media_recognizer=facades.media_recognizer,
        search_intent_agent=facades.search_intent_agent,
        tool_executor=coordinators.tool_executor,
        embedding_service=agent_rag.embedding_service,
        vector_store=agent_rag.vector_store,
        retriever=agent_rag.retriever,
        knowledge_ingestor=agent_rag.knowledge_ingestor,
        conversation_store=agent_rag.conversation_store,
        semantic_memory=agent_rag.semantic_memory,
        downloader_core=services.downloader_core,
        download_monitor=facades.download_monitor,
        filetransfer_service=services.filetransfer_service,
        transfer_pipeline=services.transfer_pipeline,
        sync_engine=services.sync_engine,
        sync_service=services.sync_service,
        file_index_service=services.file_index_service,
        indexer_service=services.indexer_service,
        subscribe_service=services.subscribe_service,
        searcher=services.searcher,
        rss_task_service=services.rss_task_service,
        filter_service=services.filter_service,
        torrent_remover_service=services.torrent_remover_service,
        brush_task_service=services.brush_task_service,
        brush_service=services.brush_service,
        site_service=services.site_service,
        site_resolver=services.site_resolver,
        site_favicon_service=services.site_favicon_service,
        media_info_service=services.media_info_service,
        media_config_service=services.media_config_service,
        media_file_service=services.media_file_service,
        media_library_service=services.media_library_service,
        media_recommendation_service=services.media_recommendation_service,
        media_server_config_service=services.media_server_config_service,
        system_config_service=services.system_config_service,
        indexer_config_service=services.indexer_config_service,
        rbac_service=services.rbac_service,
        config_service=services.config_service,
        message_sender_service=services.message_sender_service,
        message_client_service=services.message_client_service,
        scheduler_service=services.scheduler_service,
        system_info_service=services.system_info_service,
        net_test_service=services.net_test_service,
        progress_service=services.progress_service,
        web_search_service=services.web_search_service,
        search_orchestrator=services.search_orchestrator,
        backup_restore_service=services.backup_restore_service,
        user_manage_service=services.user_manage_service,
        tmdb_blacklist_service=services.tmdb_blacklist_service,
        download_service=services.download_service,
        plugin_framework_service=services.plugin_framework_service,
        storage_backend_service=services.storage_backend_service,
        search_result_service=services.search_result_service,
        transfer_history_service=services.transfer_history_service,
        subscribe_calendar_service=services.subscribe_calendar_service,
        subscribe_history_service=services.subscribe_history_service,
        words_service=services.words_service,
        user_rss_service=services.user_rss_service,
        subscription_monitor=coordinators.subscription_monitor,
        system_lifecycle=coordinators.system_lifecycle,
        alias_index=identity.alias_index,
        edition_graph=identity.edition_graph,
        identity_resolver=identity.identity_resolver,
        target_matcher=identity.target_matcher,
        identity_builder=identity.identity_builder,
        episode_remapper=identity.episode_remapper,
    )
    # 回填 PluginSandbox 的应用上下文（供插件构造命令处理器等装配对象）
    if context.plugin_sandbox is not None:
        context.plugin_sandbox._app_context = context
    log.info("[DI]对象图构建完成")
    return context
