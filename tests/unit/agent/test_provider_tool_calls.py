"""Provider 原生/回退工具调用解析单元测试"""

from typing import Any, cast
from unittest.mock import MagicMock

from app.agent.providers.base import (
    BaseProvider,
    ChatToolResponse,
    ProviderConfig,
    ToolCall,
)
from app.agent.providers.openai import OpenAIProvider


class _PlainProvider(BaseProvider):
    """无原生工具能力，走默认 prompt 协议回退"""

    _response: str = ""

    def chat(self, messages, system_prompt="", temperature=0.7, response_format=None):
        return self._response

    def is_available(self):
        return True


class TestPromptFallback:
    def _provider(self, response: str) -> _PlainProvider:
        p = _PlainProvider(ProviderConfig(name="x", api_key="", api_url="", model="m"))
        p._response = response  # type: ignore[assignment]
        return p

    def test_plain_answer(self):
        resp = self._provider("直接回答").chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "t1", "description": "x", "parameters": {}}],
        )
        assert isinstance(resp, ChatToolResponse)
        assert resp.content == "直接回答"
        assert not resp.has_tool_calls
        assert not resp.native

    def test_prompt_json_tool_call(self):
        resp = self._provider('```json\n{"tool": "system_status", "parameters": {}}\n```').chat_with_tools(
            messages=[], tools=[{"name": "system_status"}]
        )
        assert resp.has_tool_calls
        assert resp.tool_calls[0].name == "system_status"
        assert not resp.native

    def test_invalid_json_falls_through(self):
        resp = self._provider("这不是JSON").chat_with_tools(messages=[], tools=[])
        assert not resp.has_tool_calls


class TestOpenAIProviderNative:
    def _openai(self, message: dict) -> OpenAIProvider:
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = message.get("content", "")
        calls = []
        for tc in message.get("tool_calls") or []:
            call = MagicMock()
            call.id = tc.get("id", "")
            call.function.name = tc["name"]
            call.function.arguments = tc.get("arguments", "{}")
            calls.append(call)
        choice.message.tool_calls = calls or None
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        p = OpenAIProvider(ProviderConfig(name="openai", api_key="k", api_url="https://x", model="m"))
        p._client = client
        return p

    def test_native_tool_call_parsed(self):
        p = self._openai(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "system_status",
                        "arguments": '{"foo": "bar"}',
                    }
                ],
            }
        )
        resp = p.chat_with_tools(messages=[], tools=[{"name": "system_status"}])
        assert resp.native
        assert resp.has_tool_calls
        assert resp.tool_calls[0] == ToolCall(name="system_status", arguments={"foo": "bar"}, id="call_1")

    def test_native_plain_answer(self):
        p = self._openai({"content": "直接回答", "tool_calls": []})
        resp = p.chat_with_tools(messages=[], tools=[])
        assert resp.native
        assert not resp.has_tool_calls
        assert resp.content == "直接回答"

    def test_native_failure_falls_back(self):
        p = self._openai({})
        cast(Any, p._client).chat.completions.create.side_effect = RuntimeError("网络错误")
        resp = p.chat_with_tools(messages=[], tools=[{"name": "t"}], system_prompt="")
        # 回退到 prompt 协议（mock 的 create 再次抛错 → 空内容，但流程不炸）
        assert isinstance(resp, ChatToolResponse)


class TestBaseEmbeddingProviderCompat:
    def test_tool_call_dataclass(self):
        tc = ToolCall(name="a", arguments={"k": 1}, id="c1")
        assert tc.name == "a" and tc.arguments == {"k": 1}
