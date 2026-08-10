"""KnowledgeIngestor 单元测试"""

import pytest

from app.agent.providers.base import BaseEmbeddingProvider, ProviderConfig
from app.agent.rag.chunker import MarkdownChunker
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.ingestor import KnowledgeIngestor, KnowledgeLoader
from app.agent.rag.sqlite_vec_store import SQLiteVecStore


class _FakeEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, fail_on: str = ""):
        super().__init__(ProviderConfig(name="fake", api_key="", api_url="", model="m"), "m")
        self._fail_on = fail_on

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._fail_on and any(self._fail_on in t for t in texts):
            raise RuntimeError("embedding 失败")
        vectors = [[float(len(t)), 0.1] for t in texts]
        if vectors and self._dimension is None:
            self._dimension = 2
        return vectors

    def is_available(self) -> bool:
        return True


class _FakeLoader(KnowledgeLoader):
    namespace = "faq"

    def __init__(self, items: list[tuple[str, str]]):
        self._items = items

    def load(self):
        return self._items


class _FailLoader(KnowledgeLoader):
    namespace = "operations"

    def load(self):
        raise RuntimeError("加载失败")


@pytest.fixture
def store(tmp_path):
    s = SQLiteVecStore(str(tmp_path / "kb.sqlite"))
    yield s
    s.close()


def _ingestor(store, loader, fail_on=""):
    return KnowledgeIngestor(
        MarkdownChunker(chunk_size=800, overlap=100),
        EmbeddingService(_FakeEmbeddingProvider(fail_on)),
        store,
        [loader],
    )


class TestKnowledgeIngestor:
    def test_reindex_counts(self, store):
        ing = _ingestor(store, _FakeLoader([("s1", "# 标题\n内容一"), ("s2", "内容二")]))
        stats = ing.reindex()
        assert stats == {"faq": 2}
        assert store.count("faq") == 2

    def test_reindex_idempotent(self, store):
        loader = _FakeLoader([("s1", "内容")])
        ing = _ingestor(store, loader)
        ing.reindex()
        ing.reindex()
        assert store.count("faq") == 1

    def test_reindex_namespace_filter(self, store):
        ing = _ingestor(store, _FakeLoader([("s1", "内容")]))
        assert ing.reindex("operations") == {}

    def test_loader_failure_returns_zero(self, store):
        ing = _ingestor(store, _FailLoader())
        assert ing.reindex() == {"operations": 0}

    def test_embedding_failure_degrades_to_text_only(self, store):
        ing = _ingestor(store, _FakeLoader([("s1", "正常内容"), ("s2", "会失败的内容")]), fail_on="会失败")
        stats = ing.reindex()
        # 失败块按纯文本入库，仍可被全文检索命中
        assert stats["faq"] == 2
        result = store.hybrid_search("会失败的内容", None, "faq", 5)
        assert result and result[0].chunk.source == "s2"

    def test_refresh_source_replaces(self, store):
        ing = _ingestor(store, _FakeLoader([]))
        ing.refresh_source("faq", "s1", "旧内容")
        assert store.count("faq") == 1
        ing.refresh_source("faq", "s1", "新内容")
        assert store.count("faq") == 1
        result = store.hybrid_search("新内容", [0.1, 0.2], "faq", 5)
        assert result and result[0].chunk.text == "新内容"

    def test_status(self, store):
        ing = _ingestor(store, _FakeLoader([("s1", "内容")]))
        ing.reindex()
        assert ing.status() == {"faq": 1}
