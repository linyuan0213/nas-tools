"""Agent RAG + 工具层热重建 — 配置热重载后重建 RAG 能力。

RAG 对象在启动时一次性构建并固化进 frozen ToolContext / ChatAgent，
配置变更后需整体重建（retriever / ingestor / 记忆 + 工具执行器 + ChatAgent）。
"""

import log
from app.agent.tool_executor import ToolExecutor
from app.agent.tools.context import ToolContext
from app.di.builders.agent_builder import build_agent_rag
from app.di.context import AppContext
from app.services.transfer.kb_ingest_handler import register_kb_ingest_handler


def rebuild_agent_rag(context: AppContext) -> dict[str, bool]:
    """重建 Agent RAG + 记忆 + 工具层，返回各能力是否可用。"""
    rag = build_agent_rag(context.agent_service, context.media_library_service)
    object.__setattr__(context, "embedding_service", rag.embedding_service)
    object.__setattr__(context, "vector_store", rag.vector_store)
    object.__setattr__(context, "retriever", rag.retriever)
    object.__setattr__(context, "knowledge_ingestor", rag.knowledge_ingestor)
    object.__setattr__(context, "conversation_store", rag.conversation_store)
    object.__setattr__(context, "semantic_memory", rag.semantic_memory)

    tool_context = ToolContext(
        search_orchestrator=context.search_orchestrator,
        searcher=context.searcher,
        download_service=context.download_service,
        downloader_core=context.downloader_core,
        subscribe_service=context.subscribe_service,
        media_service=context.media_service,
        media_info_service=context.media_info_service,
        filetransfer_service=context.filetransfer_service,
        scheduler_service=context.scheduler_service,
        system_info_service=context.system_info_service,
        event_bus=context.event_bus,
        retriever=rag.retriever,
        conversation_store=rag.conversation_store,
        semantic_memory=rag.semantic_memory,
    )
    object.__setattr__(context, "tool_executor", ToolExecutor(ctx=tool_context))
    context.agent_service.init_chat_agent(context.tool_executor, rag.conversation_store, rag.semantic_memory)
    register_kb_ingest_handler(
        event_bus=context.event_bus,
        knowledge_ingestor=rag.knowledge_ingestor,
        thread_executor=context.thread_executor,
    )
    log.info(
        f"[DI]Agent RAG 热重建完成: retriever={rag.retriever is not None}, "
        f"ingestor={rag.knowledge_ingestor is not None}, memory={rag.semantic_memory is not None}"
    )
    return {
        "retriever": rag.retriever is not None,
        "knowledge_ingestor": rag.knowledge_ingestor is not None,
        "semantic_memory": rag.semantic_memory is not None,
    }
