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

    def chat_tool_calls(
        self, messages, tools, system_prompt="", temperature=0.7, on_token=None, on_reasoning=None, reasoning=None
    ):
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
    def _agent_provider(self, monkeypatch, tmp_path):
        """确保 get_provider() 返回可用 provider——不依赖本地 data/config.yaml 的 agent 配置（CI 全新检出无该文件）"""
        monkeypatch.setattr(
            "app.agent.config._agent_cfg",
            lambda: {
                "enabled": True,
                "default_provider": "test",
                "providers": {"test": {"api_url": "http://localhost:1", "model": "test-model"}},
            },
        )
        # 隔离 checkpoint 目录，避免读到真实 data 目录残留历史
        from app.agent import pydantic_agent as pa

        monkeypatch.setattr(pa.settings, "nexus_media_data", str(tmp_path / "data"))

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

    def test_context_restored_across_turns(self, tmp_path, monkeypatch):
        """多轮上下文：第二轮对话必须把第一轮的 user/assistant 消息恢复给模型"""
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

        captured: list = []
        original = svc.chat_tool_calls

        def _spy(messages, tools, system_prompt="", temperature=0.7, on_token=None, on_reasoning=None, reasoning=None):
            captured.append([dict(m) for m in messages])
            return original(messages, tools, system_prompt, temperature, on_token, on_reasoning, reasoning)

        monkeypatch.setattr(svc, "chat_tool_calls", _spy)

        agent.chat_with_tools("帮我搜一下 流浪地球", session_id="s3", user_id="u3")
        agent.chat_with_tools("可以", session_id="s3", user_id="u3")

        # 第二轮输入应包含第一轮的 user 问题与 assistant 回答（即"联系到上文"）
        assert captured, "模型应收到调用"
        second_turn = captured[-1]
        roles = [m.get("role") for m in second_turn]
        assert "user" in roles and "assistant" in roles
        assert any("流浪地球" in m.get("content", "") for m in second_turn if m.get("role") == "user")

    def test_checkpoint_roundtrip_rebuilds_messages(self, tmp_path, monkeypatch):
        """checkpoint 写入后可重建 pydantic-ai 消息（TypeAdapter 判别重建）"""
        agent = PydanticChatAgent(svc=_FakeSvc(), tool_executor=_FakeExecutor())
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        history = [
            ModelRequest(parts=[UserPromptPart(content="上一轮问题")]),
            ModelResponse(parts=[TextPart(content="上一轮回答")]),
        ]
        agent._checkpoint("s4", "u4", "web", history)
        restored = agent._load_checkpoint("s4", "u4", "web")
        assert len(restored) == 2
        assert isinstance(restored[0], ModelRequest)
        assert isinstance(restored[1], ModelResponse)

    def test_checkpoint_isolated_by_channel(self, tmp_path, monkeypatch):
        """checkpoint 按渠道隔离：同一 user/session 不同渠道互不影响，且清理可删除"""
        agent = PydanticChatAgent(svc=_FakeSvc(), tool_executor=_FakeExecutor())
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        history = [
            ModelRequest(parts=[UserPromptPart(content="渠道A问题")]),
            ModelResponse(parts=[TextPart(content="渠道A回答")]),
        ]
        agent._checkpoint("s5", "u5", "Telegram", history)
        assert agent._load_checkpoint("s5", "u5", "web") == []
        assert len(agent._load_checkpoint("s5", "u5", "Telegram")) == 2
        agent.clear_checkpoint("s5", "u5", "Telegram")
        assert agent._load_checkpoint("s5", "u5", "Telegram") == []
