"""ConversationStore 单元测试（真实仓储 + 隔离缓存）"""

from uuid import uuid4

import pytest

from app.agent.agents.memory import ConversationStore, MemoryKey, Summarizer
from app.db.repositories.agent_conversation_repository import AgentConversationRepository


class _FakeSummarizer(Summarizer):
    def __init__(self):
        self.calls = 0

    @property
    def ready(self):
        return True

    def summarize(self, old_summary: str, messages: list[dict]) -> str:
        self.calls += 1
        return f"摘要({len(messages)}条)"


class _DictCache:
    """测试用内存缓存（隔离全局单例）"""

    def __init__(self):
        self._data: dict = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl=None):
        self._data[key] = value
        return True

    def delete(self, key):
        self._data.pop(key, None)
        return True


@pytest.fixture(autouse=True)
def _ensure_tables():
    """仓储走全局 Database 单例（非 db_session fixture），需显式建表"""
    from app.db.models import Base
    from app.db.session import Database

    Base.metadata.create_all(Database().engine)


@pytest.fixture
def store(db_session):
    return ConversationStore(
        repo=AgentConversationRepository(),
        summarizer=_FakeSummarizer(),
        max_tokens=4000,
        keep_recent=4,
        cache=_DictCache(),
    )


@pytest.fixture
def key():
    # 唯一 session_id 隔离共享测试库（仓储走全局 Database，非 db_session）
    return MemoryKey(user_id="u1", channel="web", session_id=uuid4().hex[:12])


class TestConversationStore:
    def test_append_and_load(self, store, key):
        store.append(key, "user", "你好")
        store.append(key, "assistant", "你好，有什么可以帮你？")
        history = store.load_history(key)
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_cache_write_through(self, store, key):
        store.append(key, "user", "第一条")
        first = store.load_history(key)
        store.append(key, "user", "第二条")
        history = store.load_history(key)
        assert len(history) == 2
        assert history[1]["content"] == "第二条"
        assert first[0]["content"] == "第一条"

    def test_session_isolation(self, store, key):
        other = MemoryKey(user_id="u2", channel="web", session_id=key.session_id)
        store.append(key, "user", "u1 的话")
        assert store.load_history(other) == []

    def test_channel_isolation(self, store, key):
        tg = MemoryKey(user_id="u1", channel="telegram", session_id=key.session_id)
        store.append(key, "user", "web 端")
        assert store.load_history(tg) == []

    def test_history_for_llm_with_summary(self, store, key):
        store.append(key, "user", "问题")
        store._repo.update_summary(store._repo.get(key.user_id, key.channel, key.session_id).ID, "旧摘要", 10)
        history = store.history_for_llm(key)
        assert history[0]["role"] == "system"
        assert "旧摘要" in history[0]["content"]
        assert history[-1]["content"] == "问题"

    def test_clear_session(self, store, key):
        store.append(key, "user", "你好")
        store.clear_session(session_id=key.session_id, user_id=key.user_id, channel=key.channel)
        assert store.load_history(key) == []

    def test_rolling_summary_triggered(self, db_session, key):
        summarizer = _FakeSummarizer()
        store = ConversationStore(
            repo=AgentConversationRepository(),
            summarizer=summarizer,
            max_tokens=10,
            keep_recent=2,
            cache=_DictCache(),
        )
        for i in range(8):
            store.append(key, "user", f"第{i}条消息内容比较长" * 3)
        assert summarizer.calls > 0
        history = store.load_history(key)
        assert len(history) < 8
        conv = store._repo.get(key.user_id, key.channel, key.session_id)
        assert conv is not None
        assert conv.SUMMARY.startswith("摘要(")


class TestGetOrCreateConcurrency:
    def test_concurrent_get_or_create_same_key(self, db_session):
        """并发创建同一会话不抛唯一约束冲突"""
        from concurrent.futures import ThreadPoolExecutor

        repo = AgentConversationRepository()
        key = MemoryKey(user_id="c1", channel="web", session_id=uuid4().hex[:12])

        def _create(_):
            return repo.get_or_create(key.user_id, key.channel, key.session_id).ID

        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(_create, range(8)))
        assert len(set(ids)) == 1
        assert repo.get(key.user_id, key.channel, key.session_id) is not None
