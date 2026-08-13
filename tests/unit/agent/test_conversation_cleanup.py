"""会话过期清理单元测试"""

from datetime import datetime, timedelta

import pytest

from app.agent.agents.memory import ConversationStore, MemoryKey, Summarizer
from app.db.models.agent_memory import AGENTCONVERSATION
from app.db.repositories.agent_conversation_repository import AgentConversationRepository


@pytest.fixture(autouse=True)
def _ensure_tables():
    """仓储走全局 Database 单例（非 db_session fixture），需显式建表"""
    from app.db.models import Base
    from app.db.session import Database

    Base.metadata.create_all(Database().engine)


class _FakeSummarizer(Summarizer):
    def __init__(self):
        self.calls = 0

    @property
    def ready(self):
        return True

    def summarize(self, old_summary: str, messages: list[dict]) -> str:
        self.calls += 1
        return "摘要"


class _DictCache:
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


class TestCleanupExpired:
    def test_cleanup_removes_stale_sessions(self):
        repo = AgentConversationRepository()
        store = ConversationStore(
            repo=repo,
            summarizer=_FakeSummarizer(),
            max_tokens=4000,
            keep_recent=4,
            cache=_DictCache(),
        )
        key = MemoryKey(user_id="cu1", channel="web", session_id="stale")
        store.append(key, "user", "你好")
        # 用仓储自身会话回填 UPDATED_AT（与仓储查询同连接）
        with repo.session() as db:
            db.query(AGENTCONVERSATION).filter(AGENTCONVERSATION.SESSION_ID == "stale").update(
                {"UPDATED_AT": datetime.now() - timedelta(days=40)}
            )
        deleted = store.cleanup_expired(30)
        assert deleted >= 1
        # DB 层已删除（load_history 可能命中内存缓存，故直接查仓储）
        assert repo.get("cu1", "web", "stale") is None

    def test_cleanup_keeps_fresh_sessions(self):
        repo = AgentConversationRepository()
        store = ConversationStore(
            repo=repo,
            summarizer=_FakeSummarizer(),
            max_tokens=4000,
            keep_recent=4,
            cache=_DictCache(),
        )
        key = MemoryKey(user_id="cu2", channel="web", session_id="fresh")
        store.append(key, "user", "你好")
        deleted = store.cleanup_expired(30)
        assert deleted == 0
        assert store.load_history(key) != []

    def test_cleanup_zero_ttl_noop(self):
        repo = AgentConversationRepository()
        assert repo.cleanup_expired(0) == 0
