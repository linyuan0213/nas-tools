"""向量库单元测试（SQLiteVecStore 默认实现 + 工厂）"""

import pytest

from app.agent.rag.factory import _cpu_supports_avx2, create_vector_store
from app.agent.rag.models import Chunk
from app.agent.rag.sqlite_vec_store import SQLiteVecStore


def _chunk(cid: str, text: str, source: str = "s1", namespace: str = "faq") -> Chunk:
    return Chunk(id=cid, text=text, namespace=namespace, source=source)


def _vec(seed: float) -> list[float]:
    return [seed, 0.2, 0.3, 0.4]


@pytest.fixture
def store(tmp_path):
    s = SQLiteVecStore(str(tmp_path / "kb.sqlite"))
    yield s
    s.close()


class TestSQLiteVecStore:
    def test_upsert_and_count(self, store):
        chunks = [_chunk("a", "如何配置下载器"), _chunk("b", "电影订阅最佳实践")]
        assert store.upsert("faq", chunks, [_vec(0.1), _vec(0.9)]) == 2
        assert store.count() == 2
        assert store.count("faq") == 2
        assert store.count("messages") == 0

    def test_upsert_mismatched_lengths_raises(self, store):
        with pytest.raises(ValueError):
            store.upsert("faq", [_chunk("a", "文本")], [_vec(0.1), _vec(0.2)])

    def test_upsert_idempotent(self, store):
        chunks = [_chunk("a", "配置说明")]
        store.upsert("faq", chunks, [_vec(0.1)])
        store.upsert("faq", chunks, [_vec(0.1)])
        assert store.count() == 1

    def test_hybrid_search_fts_hit(self, store):
        chunks = [_chunk("a", "如何配置下载器 qBittorrent"), _chunk("b", "电影订阅最佳实践")]
        store.upsert("faq", chunks, [_vec(0.1), _vec(0.9)])
        results = store.hybrid_search("下载器", _vec(0.5), None, 5)
        assert results
        assert results[0].chunk.id == "a"

    def test_hybrid_search_vec_hit(self, store):
        chunks = [_chunk("a", "完全不相关的甲"), _chunk("b", "完全不相关的乙")]
        store.upsert("faq", chunks, [_vec(0.1), _vec(0.9)])
        results = store.hybrid_search("无匹配词", _vec(0.85), None, 5)
        assert results
        assert results[0].chunk.id == "b"

    def test_hybrid_search_namespace_filter(self, store):
        store.upsert("faq", [_chunk("a", "如何配置下载器")], [_vec(0.1)])
        store.upsert("messages", [_chunk("m", "如何配置下载器")], [_vec(0.1)])
        results = store.hybrid_search("下载器", _vec(0.1), "messages", 5)
        assert results
        assert all(r.chunk.namespace == "messages" for r in results)

    def test_hybrid_search_empty_store(self, store):
        assert store.hybrid_search("任何", _vec(0.1), None, 5) == []

    def test_text_only_indexing_without_vectors(self, store):
        """纯文本降级：无向量入库，FTS 可检索，向量检索自动跳过"""
        chunks = [_chunk("a", "如何配置下载器"), _chunk("b", "电影订阅实践")]
        assert store.upsert("faq", chunks, [None, None]) == 2
        assert store.count() == 2
        results = store.hybrid_search("下载器", None, None, 5)
        assert results and results[0].chunk.id == "a"
        # 有查询向量但库内向量表不存在时也不报错
        results = store.hybrid_search("下载器", _vec(0.1), None, 5)
        assert results and results[0].chunk.id == "a"

    def test_mixed_text_and_vector(self, store):
        """部分块有向量、部分纯文本"""
        chunks = [_chunk("a", "配置下载器指南"), _chunk("b", "订阅指南")]
        store.upsert("faq", chunks, [_vec(0.1), None])
        results = store.hybrid_search("下载器", _vec(0.1), None, 5)
        assert results and results[0].chunk.id == "a"

    def test_dimension_recovered_on_reopen(self, tmp_path):
        """重开已有库时从存量向量恢复维度"""
        path = str(tmp_path / "reopen.sqlite")
        s1 = SQLiteVecStore(path)
        s1.upsert("faq", [_chunk("a", "配置下载器")], [_vec(0.1)])
        s1.close()
        s2 = SQLiteVecStore(path)
        results = s2.hybrid_search("无匹配词", _vec(0.05), None, 5)
        assert results and results[0].chunk.id == "a"
        s2.close()

    def test_dimension_change_requires_reindex(self, tmp_path):
        """换 embedding 模型（维度变化）重开库时明确报错"""
        path = str(tmp_path / "dim.sqlite")
        s1 = SQLiteVecStore(path)
        s1.upsert("faq", [_chunk("a", "配置下载器")], [_vec(0.1)])
        s1.close()
        s2 = SQLiteVecStore(path)
        with pytest.raises(ValueError, match="维度不匹配"):
            s2.upsert("faq", [_chunk("b", "新内容")], [[0.1, 0.2, 0.3]])
        s2.close()

    def test_delete_by_source(self, store):
        chunks = [_chunk("a", "文档一", source="s1"), _chunk("b", "文档二", source="s2")]
        store.upsert("faq", chunks, [_vec(0.1), _vec(0.2)])
        assert store.delete_by_source("faq", "s1") == 1
        assert store.count() == 1
        assert store.delete_by_source("faq", "不存在") == 0


class TestFactory:
    def test_default_sqlite(self, tmp_path):
        store = create_vector_store({"type": "sqlite", "sqlite": {"path": str(tmp_path / "x.sqlite")}})
        assert isinstance(store, SQLiteVecStore)
        store.close()

    def test_unknown_type_fallback_sqlite(self, tmp_path):
        store = create_vector_store({"type": "unknown", "sqlite": {"path": str(tmp_path / "y.sqlite")}})
        assert isinstance(store, SQLiteVecStore)
        store.close()

    @pytest.mark.skipif(_cpu_supports_avx2(), reason="仅无 AVX2 的 CPU 可验证报错")
    def test_lancedb_requires_avx2(self):
        with pytest.raises(RuntimeError, match="AVX2"):
            create_vector_store({"type": "lancedb", "lancedb": {"path": ""}})
