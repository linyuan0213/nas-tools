"""Provider 原生/回退工具调用解析单元测试"""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.agent.providers.base import (
    BaseProvider,
    ChatToolResponse,
    ProviderConfig,
    ReasoningConfig,
    ToolCall,
    map_reasoning_effort,
)
from app.agent.providers.openai import OpenAIProvider


class _PlainProvider(BaseProvider):
    """无原生工具能力，走默认 prompt 协议回退"""

    _response: str = ""

    def chat(self, messages, system_prompt="", temperature=0.7, response_format=None, reasoning=None):
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

    def test_native_failure_raises_for_fallback_chain(self):
        p = self._openai({})
        cast(Any, p._client).chat.completions.create.side_effect = RuntimeError("网络错误")
        # 不吞错：交给 AgentService 故障转移链切换备用 Provider
        with pytest.raises(RuntimeError):
            p.chat_with_tools(messages=[], tools=[{"name": "t"}], system_prompt="")


class TestBaseEmbeddingProviderCompat:
    def test_tool_call_dataclass(self):
        tc = ToolCall(name="a", arguments={"k": 1}, id="c1")
        assert tc.name == "a" and tc.arguments == {"k": 1}


class TestMapReasoningEffort:
    def test_mapping(self):
        assert map_reasoning_effort("low") == "low"
        assert map_reasoning_effort("high") == "high"
        assert map_reasoning_effort("max") == "high"
        assert map_reasoning_effort("unknown") == "high"


class TestOpenAIReasoning:
    def _openai(self) -> OpenAIProvider:
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = "ok"
        choice.message.tool_calls = None
        resp = MagicMock()
        resp.choices = [choice]
        client.chat.completions.create.return_value = resp
        p = OpenAIProvider(ProviderConfig(name="openai", api_key="k", api_url="https://x", model="m"))
        p._client = client
        return p

    def _last_kwargs(self, p: OpenAIProvider) -> dict:
        return cast(Any, p._client).chat.completions.create.call_args.kwargs

    def test_enabled_sends_reasoning_effort(self):
        p = self._openai()
        p.chat_with_tools(messages=[], tools=[], reasoning=ReasoningConfig(effort="max"))
        assert self._last_kwargs(p)["reasoning_effort"] == "high"

    def test_disabled_sends_thinking_off(self):
        p = self._openai()
        p.chat(messages=[{"role": "user", "content": "hi"}], reasoning=ReasoningConfig(enabled=False))
        assert self._last_kwargs(p)["extra_body"] == {"thinking": {"type": "disabled"}}
        assert "reasoning_effort" not in self._last_kwargs(p)

    def test_no_reasoning_untouched(self):
        p = self._openai()
        p.chat(messages=[{"role": "user", "content": "hi"}])
        kwargs = self._last_kwargs(p)
        assert "reasoning_effort" not in kwargs
        assert "extra_body" not in kwargs

    def test_400_strips_reasoning_and_retries(self):
        p = self._openai()
        from openai import APIStatusError

        err = APIStatusError(
            "400", response=MagicMock(status_code=400), body={"error": {"message": "reasoning_effort not supported"}}
        )
        mock = cast(Any, p._client).chat.completions.create
        mock.side_effect = [err, MagicMock()]
        p.chat(messages=[{"role": "user", "content": "hi"}], reasoning=ReasoningConfig(effort="low"))
        assert mock.call_count == 2
        assert "reasoning_effort" not in mock.call_args_list[1].kwargs

    def test_400_unrelated_to_reasoning_not_retried(self):
        from openai import APIStatusError

        p = self._openai()
        err = APIStatusError(
            "400",
            response=MagicMock(status_code=400),
            body={"error": {"message": "context length exceeded"}},
        )
        mock = cast(Any, p._client).chat.completions.create
        mock.side_effect = err
        # chat() 不再吞错（否则 fallback 链失效且空结果会被缓存）；400 非推理相关不触发剥离重试
        with pytest.raises(APIStatusError):
            p.chat(messages=[{"role": "user", "content": "hi"}], reasoning=ReasoningConfig(effort="low"))
        assert mock.call_count == 1

    def test_unsupported_model_negatively_cached(self):
        from openai import APIStatusError

        p = self._openai()
        err = APIStatusError(
            "400", response=MagicMock(status_code=400), body={"error": {"message": "reasoning_effort not supported"}}
        )
        mock = cast(Any, p._client).chat.completions.create
        resp = mock.return_value
        # 三次调用：首次 400（剥离后成功）、缓存模型后再次成功
        mock.side_effect = [err, resp, resp]
        p.chat(messages=[{"role": "user", "content": "hi"}], reasoning=ReasoningConfig(effort="low"))
        assert mock.call_count == 2
        p.chat(messages=[{"role": "user", "content": "hi"}], reasoning=ReasoningConfig(effort="low"))
        assert mock.call_count == 3
        assert "reasoning_effort" not in mock.call_args_list[2].kwargs
