"""Agent RAG Builder — 创建 embedding / 向量库 / 检索器 / 采集器。"""

from dataclasses import dataclass
from typing import Any

import log
from app.agent.agents.memory import ConversationStore, SemanticMemory, Summarizer
from app.agent.config import (
    agent_enabled,
    get_embedding_config,
    get_memory_config,
    get_rag_config,
    get_vector_store_config,
)
from app.agent.providers import create_embedding_provider
from app.agent.rag.chunker import MarkdownChunker
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.factory import create_vector_store
from app.agent.rag.ingestor import KnowledgeIngestor
from app.agent.rag.loaders import default_loaders
from app.agent.rag.retriever import Retriever
from app.db.repositories.agent_conversation_repository import AgentConversationRepository


@dataclass(frozen=True)
class AgentRagObjects:
    """Agent RAG 对象组。agent 未启用或构建失败时字段为 None。"""

    embedding_service: Any | None
    vector_store: Any | None
    retriever: Any | None
    knowledge_ingestor: Any | None
    conversation_store: Any | None
    semantic_memory: Any | None


def build_agent_rag(svc: Any = None, media_library_service: Any = None) -> AgentRagObjects:
    """构建 Agent RAG + 记忆能力（svc 为 AgentService，供摘要器复用）。"""
    if not agent_enabled():
        return AgentRagObjects(None, None, None, None, None, None)
    conversation_store = _build_conversation_store(svc)
    semantic_memory = None
    emb_cfg_pre = get_embedding_config()
    if emb_cfg_pre and get_memory_config()["long_term"]["enabled"]:
        try:
            emb_provider = create_embedding_provider(emb_cfg_pre)
            semantic_memory = SemanticMemory(
                store=create_vector_store(get_vector_store_config()),
                embedding=EmbeddingService(emb_provider),
                top_k=get_memory_config()["long_term"]["top_k"],
            )
            log.info("[DI]长程语义记忆已启用（user_memory 命名空间）")
        except Exception as e:
            log.error(f"[DI]长程语义记忆构建失败: {e}")
    emb_cfg = get_embedding_config()
    if not emb_cfg:
        log.warn("[DI]agent 已启用但未配置 embedding，RAG 能力跳过")
        return AgentRagObjects(None, None, None, None, conversation_store, semantic_memory)
    try:
        embedding = EmbeddingService(create_embedding_provider(emb_cfg))
        store = create_vector_store(get_vector_store_config())
        rag_cfg = get_rag_config()
        chunker = MarkdownChunker(chunk_size=rag_cfg["chunk_size"], overlap=rag_cfg["chunk_overlap"])
        ingestor = KnowledgeIngestor(chunker, embedding, store, default_loaders(media_library_service))
        retriever = Retriever(embedding, store, top_k=rag_cfg["top_k"], rerank_top_k=rag_cfg["rerank_top_k"])
        log.info("[DI]Agent RAG 构建完成")
        return AgentRagObjects(
            embedding_service=embedding,
            vector_store=store,
            retriever=retriever,
            knowledge_ingestor=ingestor,
            conversation_store=conversation_store,
            semantic_memory=semantic_memory,
        )
    except Exception as e:
        log.error(f"[DI]Agent RAG 构建失败，降级为无 RAG: {e}")
        return AgentRagObjects(None, None, None, None, conversation_store, semantic_memory)


def _build_conversation_store(svc: Any) -> ConversationStore | None:
    """短程记忆存储（DB 持久化 + 滚动摘要）"""
    mem_cfg = get_memory_config()
    short = mem_cfg.get("short_term") or {}
    try:
        return ConversationStore(
            repo=AgentConversationRepository(),
            summarizer=Summarizer(svc),
            max_tokens=short.get("max_tokens", 4000),
        )
    except Exception as e:
        log.error(f"[DI]ConversationStore 构建失败: {e}")
        return None
