"""EmbeddingService 单元测试（Fake provider）"""

from app.agent.providers.base import BaseEmbeddingProvider, ProviderConfig
from app.agent.rag.embedding import EmbeddingService


class _FakeEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, fail: bool = False):
        super().__init__(ProviderConfig(name="fake", api_key="", api_url="", model="fake-emb"), "fake-emb")
        self._fail = fail
        self.call_count = 0
        self.embedded_texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("provider 不可用")
        self.embedded_texts.extend(texts)
        vectors = [[float(len(t)), 0.1, 0.2] for t in texts]
        if vectors and self._dimension is None:
            self._dimension = 3
        return vectors

    def is_available(self) -> bool:
        return not self._fail


class TestEmbeddingService:
    def test_embed_texts_basic(self):
        svc = EmbeddingService(_FakeEmbeddingProvider())
        results = svc.embed_texts(["你好", "世界"])
        assert len(results) == 2
        assert results[0] == [2.0, 0.1, 0.2]
        assert svc.dimension == 3

    def test_empty_input(self):
        svc = EmbeddingService(_FakeEmbeddingProvider())
        assert svc.embed_texts([]) == []

    def test_batching(self):
        provider = _FakeEmbeddingProvider()
        svc = EmbeddingService(provider, batch_size=2)
        svc.embed_texts(["a", "b", "c", "d", "e"])
        assert provider.call_count == 3

    def test_cache_hit_skips_provider(self):
        provider = _FakeEmbeddingProvider()
        svc = EmbeddingService(provider)
        svc.embed_texts(["缓存文本"])
        calls_after_first = provider.call_count
        svc.embed_texts(["缓存文本"])
        assert provider.call_count == calls_after_first

    def test_failure_returns_none_and_not_cached(self):
        provider = _FakeEmbeddingProvider(fail=True)
        svc = EmbeddingService(provider)
        results = svc.embed_texts(["会失败"])
        assert results == [None]
        provider._fail = False
        results = svc.embed_texts(["会失败"])
        assert results[0] is not None

    def test_embed_query(self):
        svc = EmbeddingService(_FakeEmbeddingProvider())
        assert svc.embed_query("单条") == [2.0, 0.1, 0.2]
