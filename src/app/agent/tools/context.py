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
    retriever: Any = None
    conversation_store: Any = None
    semantic_memory: Any = None
