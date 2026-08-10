"""RAG Pipeline — 知识库分块 / 向量化 / 存储 / 检索

LanceDBStore 不在此导出：lancedb 原生库在无 AVX2 的 CPU 上 import 即 SIGILL，
只能通过 create_vector_store 工厂惰性加载。
"""

from app.agent.rag.chunker import MarkdownChunker
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.factory import create_vector_store, resolve_store_path
from app.agent.rag.ingestor import KnowledgeIngestor, KnowledgeLoader
from app.agent.rag.loaders import DocsLoader, MessageTemplateLoader, OperationsLoader, default_loaders
from app.agent.rag.models import Chunk, ScoredChunk
from app.agent.rag.namespaces import Namespace
from app.agent.rag.retriever import RetrievalResult, Retriever
from app.agent.rag.sqlite_vec_store import SQLiteVecStore
from app.agent.rag.vector_store import VectorStore

__all__ = [
    "Chunk",
    "ScoredChunk",
    "MarkdownChunker",
    "EmbeddingService",
    "VectorStore",
    "SQLiteVecStore",
    "create_vector_store",
    "resolve_store_path",
    "KnowledgeLoader",
    "KnowledgeIngestor",
    "DocsLoader",
    "OperationsLoader",
    "MessageTemplateLoader",
    "default_loaders",
    "Namespace",
    "Retriever",
    "RetrievalResult",
]
