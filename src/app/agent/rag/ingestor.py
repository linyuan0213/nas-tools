"""知识库采集器 — 加载 → 分块 → 向量化 → 入库，支持全量重建与按来源增量刷新"""

from abc import ABC, abstractmethod
from collections.abc import Iterable

import log
from app.agent.rag.chunker import MarkdownChunker
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.vector_store import VectorStore


class KnowledgeLoader(ABC):
    """知识来源加载器 — 每个来源一个实现"""

    namespace: str = ""

    @abstractmethod
    def load(self) -> Iterable[tuple[str, str]]:
        """产出 (source, text) 序列"""


class KnowledgeIngestor:
    """知识库采集器"""

    def __init__(
        self,
        chunker: MarkdownChunker,
        embedding: EmbeddingService,
        store: VectorStore,
        loaders: list[KnowledgeLoader],
    ):
        self._chunker = chunker
        self._embedding = embedding
        self._store = store
        self._loaders = loaders

    def reindex(self, namespace: str | None = None) -> dict[str, int]:
        """重建索引：按来源先删后写（幂等）。返回 {namespace: 写入块数}"""
        stats: dict[str, int] = {}
        for loader in self._loaders:
            if namespace and loader.namespace != namespace:
                continue
            stats[loader.namespace] = self._reindex_loader(loader)
        return stats

    def refresh_source(self, namespace: str, source: str, text: str) -> int:
        """单来源增量刷新"""
        self._store.delete_by_source(namespace, source)
        return self._ingest_text(namespace, source, text)

    def status(self) -> dict[str, int]:
        """各命名空间块数"""
        return {loader.namespace: self._store.count(loader.namespace) for loader in self._loaders}

    def _reindex_loader(self, loader: KnowledgeLoader) -> int:
        total = 0
        try:
            items = list(loader.load())
        except Exception as e:
            log.error(f"[Ingestor]加载失败: {loader.namespace}: {e}")
            return 0
        for source, text in items:
            self._store.delete_by_source(loader.namespace, source)
            total += self._ingest_text(loader.namespace, source, text)
        log.info(f"[Ingestor]{loader.namespace} 索引完成: {len(items)} 来源, {total} 块")
        return total

    def _ingest_text(self, namespace: str, source: str, text: str) -> int:
        chunks = self._chunker.split(text, source, namespace)
        if not chunks:
            return 0
        vectors = self._embedding.embed_texts([c.text for c in chunks])
        failed = sum(1 for v in vectors if v is None)
        if failed:
            # embedding 不可用时按纯文本入库（仅全文检索），配好 embedding 重建后自动升级混合检索
            log.warn(f"[Ingestor]{source}: {failed}/{len(chunks)} 块 embedding 失败，按纯文本入库")
        return self._store.upsert(namespace, chunks, vectors)


__all__ = ["KnowledgeLoader", "KnowledgeIngestor"]
