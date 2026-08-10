"""检索器 — 混合检索 + 截断 + 引用组装"""

from dataclasses import dataclass, field

import log
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.models import ScoredChunk
from app.agent.rag.vector_store import VectorStore


@dataclass(frozen=True)
class RetrievalResult:
    """检索结果：chunks + 引用"""

    chunks: list[ScoredChunk] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        return bool(self.chunks)


class Retriever:
    """知识库检索器"""

    def __init__(
        self,
        embedding: EmbeddingService,
        store: VectorStore,
        top_k: int = 6,
        rerank_top_k: int = 3,
        max_chars: int = 500,
    ):
        self._embedding = embedding
        self._store = store
        self._top_k = top_k
        self._rerank_top_k = rerank_top_k
        self._max_chars = max_chars

    def search(self, query: str, namespace: str | None = None) -> RetrievalResult:
        """混合检索：embedding 失败时退化为纯全文检索"""
        if not query or not query.strip():
            return RetrievalResult()
        vector = self._embedding.embed_query(query)
        if vector is None:
            log.warn("[Retriever]embedding 失败，退化为纯全文检索")
        hits = self._store.hybrid_search(query, vector, namespace, self._top_k)
        hits = hits[: self._rerank_top_k]
        citations = [
            {
                "source": h.chunk.source,
                "heading": h.chunk.metadata.get("heading", ""),
                "snippet": h.chunk.text[: self._max_chars],
            }
            for h in hits
        ]
        return RetrievalResult(chunks=hits, citations=citations)
