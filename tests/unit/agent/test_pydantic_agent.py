"""PydanticChatAgent（pydantic-ai 引擎）功能测试 — mock AgentService 与 ToolExecutor

验证：多步工具循环（模型先调工具→工具结果回灌→最终回答）、事件、checkpoint。
"""

from typing import cast

import pytest

from app.agent.agents.memory import ConversationStore, Summarizer
from app.agent.pydantic_agent import PydanticChatAgent
from app.agent.tools.base import ToolResult
from app.db.repositories.agent_conversation_repository import AgentConversationRepository


class _FakeSvc:
    """模拟 AgentService：先返回一次工具调用，再返回最终回答"""

    def __init__(self):
        self.ready = True

    def chat_tool_calls(self, messages, tools, system_prompt="", temperature=0.7, on_token=None, on_reasoning=None):
        from app.agent.providers.base import ChatToolResponse, ToolCall

        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if not has_tool_result:
            return ChatToolResponse(
                content="", tool_calls=[ToolCall(name="media_search", arguments={"title": "流浪地球"})], native=True
            )
        return ChatToolResponse(content="找到了《流浪地球》的资源。", tool_calls=[])

    def chat(self, messages, system_prompt=""):
        return "单轮回答"

    def is_available(self):
        return True


class _FakeExecutor:
    def __init__(self):
        self.executed = []

    def list_tools(self):
        return [
            {
                "name": "media_search",
                "description": "搜索影视资源",
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string", "description": "标题"}},
                    "required": ["title"],
                },
            }
        ]

    def get_schema(self, name):
        return {"name": name, "level": "read", "description": "搜索影视资源"}

    def execute(self, tool_name, arguments, **kwargs):
        self.executed.append((tool_name, arguments))
        return ToolResult(success=True, data={"total": 5, "results": ["a"]})


class _FakeSummarizer(Summarizer):
    def __init__(self):
        self.calls = 0

    @property
    def ready(self):
        return True

    def summarize(self, old_summary, messages):
        return "摘要"


class _DictCache:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl=None):
        self._data[key] = value

    def delete(self, key):
        self._data.pop(key, None)


class _FakeRepo:
    """内存版会话仓储：get_or_create 返回固定 id，get 返回固定 conv"""

    class _Conv:
        ID = 1
        SUMMARY = ""
        TOKEN_USAGE = 0

    def __init__(self):
        self.rows = []

    def get(self, user_id, channel, session_id):
        return None if not self.rows else self._Conv()

    def get_or_create(self, user_id, channel, session_id):
        return self._Conv()

    def append_message(self, conversation_id, role, content, tokens=0, tool_calls=None):
        self.rows.append({"role": role, "content": content, "tool_calls": tool_calls, "created_at": 0})

    def get_messages(self, conversation_id):
        return []

    def update_summary(self, conversation_id, summary, token_usage):
        pass

    def delete_conversation(self, user_id, channel, session_id):
        self.rows = []

    def cleanup_expired(self, ttl_days):
        return 0


class TestPydanticChatAgent:
    @pytest.fixture(autouse=True)
    def _agent_provider(self, monkeypatch):
        """确保 get_provider() 返回可用 provider——不依赖本地 data/config.yaml 的 agent 配置（CI 全新检出无该文件）"""
        monkeypatch.setattr(
            "app.agent.config._agent_cfg",
            lambda: {
                "enabled": True,
                "default_provider": "test",
                "providers": {"test": {"api_url": "http://localhost:1", "model": "test-model"}},
            },
        )

    def test_multi_step_tool_loop(self, tmp_path):
        svc = _FakeSvc()
        executor = _FakeExecutor()
        repo = _FakeRepo()
        store = ConversationStore(
            repo=cast(AgentConversationRepository, repo),
            summarizer=_FakeSummarizer(),
            max_tokens=4000,
            keep_recent=10,
            cache=_DictCache(),
        )
        agent = PydanticChatAgent(svc=svc, tool_executor=executor, memory=store)
        events = []
        answer = agent.chat_with_tools("帮我搜一下 流浪地球", session_id="s1", user_id="u1", on_event=events.append)
        assert answer == "找到了《流浪地球》的资源。"
        assert executor.executed, "工具应被执行"
        assert executor.executed[0][0] == "media_search"
        assert executor.executed[0][1] == {"title": "流浪地球"}, "工具参数应透传（p_ 前缀回归）"
        assert any(e.get("type") == "tool_call" for e in events)
        assert any(e.get("type") == "tool_result" for e in events)

    def test_ask_and_translate(self):
        svc = _FakeSvc()
        agent = PydanticChatAgent(svc=svc, tool_executor=_FakeExecutor())
        assert agent.ask("你好") == "单轮回答"
        assert agent.translate_to_zh("hello") == "单轮回答"

    def test_memory_persisted(self):
        svc = _FakeSvc()
        executor = _FakeExecutor()
        repo = _FakeRepo()
        store = ConversationStore(
            repo=cast(AgentConversationRepository, repo),
            summarizer=_FakeSummarizer(),
            max_tokens=4000,
            keep_recent=10,
            cache=_DictCache(),
        )
        agent = PydanticChatAgent(svc=svc, tool_executor=executor, memory=store)
        agent.chat_with_tools("帮我搜一下 流浪地球", session_id="s2", user_id="u2")
        assert any(r["role"] == "user" for r in repo.rows)
        assert any(r["role"] == "assistant" for r in repo.rows)
