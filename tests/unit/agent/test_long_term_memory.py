"""长程语义记忆（SemanticMemory）单元测试"""

import pytest

from app.agent.agents.memory import SemanticMemory, extract_facts
from app.agent.providers.base import BaseEmbeddingProvider, ProviderConfig
from app.agent.rag.embedding import EmbeddingService
from app.agent.rag.sqlite_vec_store import SQLiteVecStore


class _Emb(BaseEmbeddingProvider):
    def __init__(self):
        super().__init__(ProviderConfig(name="e", api_key="", api_url="", model="m"), "m")

    def embed(self, texts):
        vecs = [[float(hash(t) % 500) / 500.0, 0.1, 0.2] for t in texts]
        if vecs and self._dimension is None:
            self._dimension = 3
        return vecs

    def is_available(self):
        return True


@pytest.fixture
def memory(tmp_path):
    store = SQLiteVecStore(str(tmp_path / "mem.sqlite"))
    m = SemanticMemory(store, EmbeddingService(_Emb()), top_k=5)
    yield m
    store.close()


class TestSemanticMemory:
    def test_add_and_search(self, memory):
        assert memory.add_memory("u1", "用户偏好 4K REMUX 资源")
        assert memory.add_memory("u1", "喜欢科幻电影")
        hits = memory.search("u1", "喜欢什么画质")
        assert hits  # 向量/全文命中
        assert any("4K" in h for h in hits)

    def test_add_idempotent(self, memory):
        memory.add_memory("u1", "偏好 4K")
        memory.add_memory("u1", "偏好 4K")
        assert len(memory.list("u1")) == 1

    def test_search_scoped_to_user(self, memory):
        memory.add_memory("u1", "偏好 4K")
        memory.add_memory("u2", "偏好 1080p")
        hits = memory.search("u1", "画质偏好")
        assert hits
        assert all("4K" in h for h in hits)

    def test_forget_by_text(self, memory):
        memory.add_memory("u1", "偏好 4K REMUX")
        memory.add_memory("u1", "喜欢科幻电影")
        deleted = memory.forget("u1", "4K")
        assert deleted >= 1
        hits = memory.search("u1", "4K")
        # 目标记忆被删除；其他无关记忆不连带删除
        assert "偏好 4K REMUX" not in hits

    def test_forget_empty_noop(self, memory):
        memory.add_memory("u1", "偏好 4K")
        assert memory.forget("u1", "") == 0

    def test_empty_text_not_added(self, memory):
        assert not memory.add_memory("u1", "   ")


class TestExtractFacts:
    def test_returns_empty_when_not_ready(self):
        svc = type("S", (), {"ready": False, "chat": lambda *a, **k: "x"})()
        assert extract_facts(svc, []) == []

    def test_parses_lines(self):
        svc = type("S", (), {"ready": True, "chat": lambda *a, **k: "- 偏好 4K REMUX\n- 只下载 FREE 种子"})()
        facts = extract_facts(svc, [{"role": "user", "content": "我喜欢4K"}, {"role": "assistant", "content": "好的"}])
        assert "偏好 4K REMUX" in facts
        assert "只下载 FREE 种子" in facts

    def test_failure_returns_empty(self):
        svc = type("S", (), {"ready": True, "chat": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))})()
        assert extract_facts(svc, []) == []
