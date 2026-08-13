"""消息命令处理器工厂 — Webhook 与内置消息页共用的单例装配

交互式搜索的分页缓存随实例存活，必须跨消息复用同一实例，
否则列表消息发出后回复序号时缓存已随实例销毁。
"""

import threading

from app.di.context import AppContext
from app.message.message import Message
from app.services.search_message_service import MessageSearchService
from app.services.system.message import MessageCommandHandler

_handlers_lock = threading.Lock()
_search_service: MessageSearchService | None = None
_command_handler: MessageCommandHandler | None = None


def get_message_command_handler(app_context: AppContext, message: Message) -> MessageCommandHandler:
    """搜索/命令处理器单例"""
    global _search_service, _command_handler
    with _handlers_lock:
        if _search_service is None:
            _search_service = MessageSearchService(
                downloader=app_context.downloader_core,
                searcher=app_context.searcher,
                indexer=app_context.indexer_service,
                site_cache=app_context.site_cache,
                site_engine=app_context.site_engine,
                subscribe_service=app_context.subscribe_service,
                media_service=app_context.media_service,
                agent_service=app_context.agent_service,
                message=message,
            )
        if _command_handler is None:
            _command_handler = MessageCommandHandler(
                search_handler=_search_service,
                torrent_remover_service=app_context.torrent_remover_service,
                downloader_core=app_context.downloader_core,
                sync_service=app_context.sync_service,
                filetransfer_service=app_context.filetransfer_service,
                event_bus=app_context.event_bus,
                thread_executor=app_context.thread_executor,
                message=message,
                subscription_monitor=app_context.subscription_monitor,
                rss_task_service=app_context.rss_task_service,
                subscribe_service=app_context.subscribe_service,
                site_service=app_context.site_service,
                system_lifecycle=app_context.system_lifecycle,
            )
    return _command_handler


def reset_message_handlers() -> None:
    """重置处理器单例（测试用）"""
    global _search_service, _command_handler
    with _handlers_lock:
        _search_service = None
        _command_handler = None
