"""Embedding 服务门面 — 批处理 + 缓存"""

import hashlib

import log
from app.agent.providers.base import BaseEmbeddingProvider
from app.infrastructure.cache_system import get_cache_manager


class EmbeddingService:
    """Embedding 服务 — 分批调用 + 按文本缓存（key=sha1(model+text)）"""

    def __init__(self, provider: BaseEmbeddingProvider, batch_size: int = 32):
        self._provider = provider
        self._batch_size = batch_size
        self._cache = get_cache_manager().get_or_create(
            "agent_embedding", cache_type="memory", maxsize=4096, ttl=24 * 3600
        )

    @property
    def dimension(self) -> int:
        return self._provider.dimension

    @property
    def ready(self) -> bool:
        return self._provider is not None

    def _cache_key(self, text: str) -> str:
        raw = f"{self._provider.name}:{getattr(self._provider, '_model', '')}:{text}"
        return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()

    def _embed_chunked(self, texts: list[str], size: int) -> list[list[float] | None]:
        """分批转向量；单批失败时自动缩小批次重试（适配各 provider 批次上限）"""
        out: list[list[float] | None] = []
        for start in range(0, len(texts), size):
            chunk = texts[start : start + size]
            try:
                out.extend(self._provider.embed(chunk))
            except Exception as e:
                if size <= 1:
                    log.warn(f"[EmbeddingService]embed 失败: {e}，{len(chunk)} 条置空")
                    out.extend([None] * len(chunk))
                else:
                    log.warn(f"[EmbeddingService]批量 embed 失败，缩小批次重试: {e}")
                    out.extend(self._embed_chunked(chunk, max(1, size // 2)))
        return out

    def embed_texts(self, texts: list[str]) -> list[list[float] | None]:
        """批量转向量，逐条缓存；失败条返回 None，不污染缓存"""
        if not texts:
            return []
        results: list[list[float] | None] = [None] * len(texts)
        missing: list[int] = []
        for i, text in enumerate(texts):
            cached = self._cache.get(self._cache_key(text))
            if cached is not None:
                results[i] = cached
            else:
                missing.append(i)

        for start in range(0, len(missing), self._batch_size):
            batch_idx = missing[start : start + self._batch_size]
            batch_texts = [texts[i] for i in batch_idx]
            vectors = self._embed_chunked(batch_texts, self._batch_size)
            for i, vector in zip(batch_idx, vectors, strict=False):
                if vector is None:
                    continue
                results[i] = vector
                self._cache.set(self._cache_key(texts[i]), vector)
        return results

    def embed_query(self, text: str) -> list[float] | None:
        """单条查询转向量"""
        return self.embed_texts([text])[0]
