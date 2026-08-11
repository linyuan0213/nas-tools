"""ChatAgent 多步循环单元测试（Fake svc + Fake executor）"""

from app.agent.agents.chat_agent import ChatAgent
from app.agent.agents.memory import ConversationStore
from app.agent.providers.base import ChatToolResponse, ToolCall
from app.agent.tools.base import ToolResult


class _FakeSvc:
    def __init__(self, responses: list[ChatToolResponse], ready: bool = True):
        self._responses = list(responses)
        self._ready = ready
        self.calls: list[list[dict]] = []

    @property
    def ready(self):
        return self._ready

    def chat_tool_calls(self, messages, tools, temperature=0.7):
        self.calls.append(messages)
        return self._responses.pop(0) if self._responses else ChatToolResponse(content="（无更多响应）")

    def chat(self, messages, system_prompt="", use_cache=False, **kwargs):
        return "ok"


class _FakeExecutor:
    def __init__(self, results: list[ToolResult]):
        self._results = list(results)
        self.executed: list[tuple] = []

    def list_tools(self):
        return [{"name": "system_status", "description": "x", "parameters": {}, "level": "read"}]

    def tool_names(self):
        return ["system_status"]

    def get_schema(self, name):
        return {"name": name}

    def execute(self, name, arguments, **kwargs):
        self.executed.append((name, arguments))
        return self._results.pop(0) if self._results else ToolResult(success=True, data={})


class _FakeMemory(ConversationStore):
    def __init__(self):
        self.history: list[dict] = []
        self.appended: list[tuple] = []

    def history_for_llm(self, key):
        return list(self.history)

    def append(self, key, role, content, tool_calls=None):
        self.appended.append((role, content))


def _tool_call(name="system_status", args=None, cid="call_1", native=True) -> ChatToolResponse:
    return ChatToolResponse(content="", tool_calls=[ToolCall(name=name, arguments=args or {}, id=cid)], native=native)


class TestChatLoop:
    def test_direct_answer_no_tool(self):
        svc = _FakeSvc([ChatToolResponse(content="你好，有什么可以帮你？")])
        agent = ChatAgent(svc=svc, tool_executor=_FakeExecutor([]))
        assert agent.chat_with_tools("你好") == "你好，有什么可以帮你？"
        assert len(svc.calls) == 1

    def test_native_tool_call_loop(self):
        svc = _FakeSvc([_tool_call(), ChatToolResponse(content="当前 CPU 占用 30%。")])
        executor = _FakeExecutor([ToolResult(success=True, data={"cpu": 30})])
        agent = ChatAgent(svc=svc, tool_executor=executor)
        answer = agent.chat_with_tools("系统负载怎么样")
        assert answer == "当前 CPU 占用 30%。"
        assert executor.executed == [("system_status", {})]
        # 原生协议：工具结果以 tool role 消息回灌
        assert svc.calls[1][-1]["role"] == "tool"
        assert svc.calls[1][-1]["tool_call_id"] == "call_1"

    def test_multi_step_native_loop(self):
        svc = _FakeSvc([_tool_call(), _tool_call(cid="call_2"), ChatToolResponse(content="两步查询完成。")])
        executor = _FakeExecutor([ToolResult(success=True, data={"a": 1}), ToolResult(success=True, data={"b": 2})])
        agent = ChatAgent(svc=svc, tool_executor=executor)
        answer = agent.chat_with_tools("查两次状态")
        assert answer == "两步查询完成。"
        assert len(executor.executed) == 2
        assert len(svc.calls) == 3

    def test_prompt_fallback_tool_call(self):
        """非原生 provider：prompt 协议解析出的工具调用同样执行"""
        svc = _FakeSvc([_tool_call(native=False), ChatToolResponse(content="完成。")])
        executor = _FakeExecutor([ToolResult(success=True, data={})])
        agent = ChatAgent(svc=svc, tool_executor=executor)
        answer = agent.chat_with_tools("查状态")
        assert answer == "完成。"
        # 回退协议：工具结果以 user [工具结果] 消息回灌
        assert svc.calls[1][-1]["role"] == "user"
        assert "[工具结果]" in svc.calls[1][-1]["content"]

    def test_max_steps_guard(self):
        svc = _FakeSvc([_tool_call()] * 20)
        executor = _FakeExecutor([ToolResult(success=True, data={})] * 20)
        agent = ChatAgent(svc=svc, tool_executor=executor, max_steps=3)
        answer = agent.chat_with_tools("循环")
        assert "步骤过多" in answer
        assert len(svc.calls) == 3

    def test_need_confirm_breaks_loop(self):
        svc = _FakeSvc([_tool_call()])
        executor = _FakeExecutor([ToolResult(success=True, need_confirm=True, data={"message": "删除任务需确认"})])
        agent = ChatAgent(svc=svc, tool_executor=executor)
        answer = agent.chat_with_tools("删掉任务")
        assert "需要确认" in answer
        assert len(svc.calls) == 1

    def test_tool_error_fed_back(self):
        svc = _FakeSvc([_tool_call(), ChatToolResponse(content="查询失败了。")])
        executor = _FakeExecutor([ToolResult(success=False, error="下载器离线")])
        agent = ChatAgent(svc=svc, tool_executor=executor)
        answer = agent.chat_with_tools("查状态")
        assert answer == "查询失败了。"
        assert "下载器离线" in svc.calls[1][-1]["content"]

    def test_memory_persisted(self):
        svc = _FakeSvc([ChatToolResponse(content="回答")])
        memory = _FakeMemory()
        agent = ChatAgent(svc=svc, tool_executor=_FakeExecutor([]), memory=memory)
        agent.chat_with_tools("问题", session_id="s1", user_id="u1")
        assert ("user", "问题") in memory.appended
        assert ("assistant", "回答") in memory.appended

    def test_history_loaded_into_messages(self):
        svc = _FakeSvc([ChatToolResponse(content="回答")])
        memory = _FakeMemory()
        memory.history = [{"role": "user", "content": "之前的问题"}]
        agent = ChatAgent(svc=svc, tool_executor=_FakeExecutor([]), memory=memory)
        agent.chat_with_tools("新问题", session_id="s1")
        contents = [m["content"] for m in svc.calls[0]]
        assert "之前的问题" in contents
        assert "新问题" in contents

    def test_on_event_emitted(self):
        svc = _FakeSvc([_tool_call(), ChatToolResponse(content="完成")])
        executor = _FakeExecutor([ToolResult(success=True, data={})])
        events: list[dict] = []
        agent = ChatAgent(svc=svc, tool_executor=executor)
        agent.chat_with_tools("查状态", on_event=events.append)
        types = [e["type"] for e in events]
        assert types == ["tool_call", "tool_result"]

    def test_not_ready(self):
        agent = ChatAgent(svc=_FakeSvc([], ready=False), tool_executor=_FakeExecutor([]))
        assert agent.chat_with_tools("你好") == "AI 服务未配置"
