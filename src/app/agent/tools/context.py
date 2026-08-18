"""工具执行上下文 — 类型化依赖注入（替代旧 deps dict）"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    """工具执行上下文 — 仅含 MVP 工具所需的最小服务集合"""

    search_orchestrator: Any
    searcher: Any
    download_service: Any
    downloader_core: Any
    subscribe_service: Any
    media_service: Any
    media_info_service: Any
    filetransfer_service: Any
    scheduler_service: Any
    system_info_service: Any
    event_bus: Any
    site_service: Any = None
    brush_service: Any = None
    media_library_service: Any = None
    transfer_history_service: Any = None
    user_rss_service: Any = None
    knowledge_ingestor: Any = None
    indexer_service: Any = None
    torrent_remover_service: Any = None
    storage_backend_service: Any = None
    words_service: Any = None
    plugin_framework_service: Any = None
    retriever: Any = None
    conversation_store: Any = None
    semantic_memory: Any = None
