"""Retriever 单元测试"""

import pytest

from app.agent.providers.base import BaseEmbeddingProvider, ProviderConfig
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.models import Chunk
from app.agent.rag.retriever import Retriever
from app.agent.rag.sqlite_vec_store import SQLiteVecStore


class _FakeEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, fail: bool = False):
        super().__init__(ProviderConfig(name="fake", api_key="", api_url="", model="m"), "m")
        self._fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._fail:
            raise RuntimeError("embedding 不可用")
        vectors = [[0.1 if "下载" in t else 0.9, 0.2, 0.3] for t in texts]
        if vectors and self._dimension is None:
            self._dimension = 3
        return vectors

    def is_available(self) -> bool:
        return not self._fail


@pytest.fixture
def retriever(tmp_path):
    store = SQLiteVecStore(str(tmp_path / "kb.sqlite"))
    embedding = EmbeddingService(_FakeEmbeddingProvider())
    chunks = [
        Chunk(id="a", text="如何配置下载器 qBittorrent 的连接参数", namespace="faq", source="docs/a.md"),
        Chunk(id="b", text="电影订阅的最佳实践", namespace="faq", source="docs/b.md"),
        Chunk(id="c", text="下载完成通知模板", namespace="messages", source="message_template/download_start"),
    ]
    vectors = embedding.embed_texts([c.text for c in chunks])
    store.upsert("faq", chunks[:2], [v for v in vectors[:2] if v is not None])
    store.upsert("messages", chunks[2:], [v for v in vectors[2:] if v is not None])
    r = Retriever(embedding, store, top_k=6, rerank_top_k=3, max_chars=10)
    yield r
    store.close()


class TestRetriever:
    def test_search_hit_with_citations(self, retriever):
        result = retriever.search("下载器配置", namespace="faq")
        assert result.hit
        assert result.citations
        assert result.citations[0]["source"].startswith("docs/")
        assert len(result.citations[0]["snippet"]) <= 10

    def test_search_empty_query(self, retriever):
        assert not retriever.search("").hit
        assert not retriever.search("   ").hit

    def test_search_namespace_filter(self, retriever):
        result = retriever.search("下载", namespace="messages")
        assert result.hit
        assert all("message_template" in c["source"] for c in result.citations)

    def test_search_embedding_failure_degrades_to_fts(self, tmp_path):
        store = SQLiteVecStore(str(tmp_path / "kb2.sqlite"))
        good = EmbeddingService(_FakeEmbeddingProvider())
        chunk = Chunk(id="x", text="如何配置下载器", namespace="faq", source="docs/x.md")
        v = good.embed_query(chunk.text)
        assert v is not None
        store.upsert("faq", [chunk], [v])
        failing = Retriever(EmbeddingService(_FakeEmbeddingProvider(fail=True)), store)
        result = failing.search("下载器")
        assert result.hit
        assert result.citations[0]["source"] == "docs/x.md"
        store.close()
