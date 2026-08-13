"""AgentService 故障转移 / 用量日志 / 脱敏 单元测试"""

import pytest

from app.agent.context import ContextBuilder
from app.agent.providers.base import ProviderConfig
from app.agent.service import AgentService, sanitize


class _FakeProvider:
    def __init__(self, name, fail=False):
        self._config = ProviderConfig(name=name, api_key="sk-test", api_url="", model="m")
        self._fail = fail
        self.calls = 0

    def chat(self, messages, system_prompt="", temperature=0.7, response_format=None):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self._config.name} 挂了")
        return f"{self._config.name} 回答"

    def chat_with_tools(self, messages, tools, system_prompt="", temperature=0.7):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self._config.name} 挂了")
        return f"{self._config.name} tools 回答"

    def chat_with_tools_stream(
        self, messages, tools, system_prompt="", temperature=0.7, on_token=None, on_reasoning=None
    ):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self._config.name} 挂了")
        text = f"{self._config.name} tools 回答"
        if on_token:
            on_token(text)
        if on_reasoning:
            on_reasoning("thinking")
        return text


@pytest.fixture
def service():
    svc = AgentService()
    svc._enabled = True
    svc._provider = _FakeProvider("main", fail=False)
    svc._fallbacks = [_FakeProvider("backup", fail=False)]
    return svc


class TestFallback:
    def test_main_provider_success(self, service):
        assert service.chat([{"role": "user", "content": "hi"}], use_cache=False) == "main 回答"
        assert service._provider.calls == 1

    def test_fallback_to_backup(self, service):
        service._provider._fail = True
        result = service.chat([{"role": "user", "content": "hi"}], use_cache=False)
        assert result == "backup 回答"
        assert service._fallbacks[0].calls == 1

    def test_all_fail_raises(self, service):
        service._provider._fail = True
        service._fallbacks[0]._fail = True
        with pytest.raises(RuntimeError):
            service.chat([{"role": "user", "content": "hi"}], use_cache=False)

    def test_fallback_chain_empty_raises(self, service):
        service._provider = None
        service._fallbacks = []
        with pytest.raises(RuntimeError):
            service.chat([{"role": "user", "content": "hi"}], use_cache=False)

    def test_ready_with_fallback_only(self, service):
        service._provider = None
        assert service.ready  # fallback 存在即可用

    def test_tool_calls_fallback(self, service):
        service._provider._fail = True
        result = service.chat_tool_calls(messages=[], tools=[])
        assert result == "backup tools 回答"


class TestUsageLog:
    def test_usage_logged_on_success(self, service):
        calls: list[dict] = []
        service._log_usage = lambda **kw: calls.append(kw)
        service.chat([{"role": "user", "content": "hi"}], use_cache=False)
        assert calls
        assert calls[0]["provider"] == "main"
        assert calls[0]["ms"] >= 0

    def test_usage_logged_on_fallback(self, service):
        calls: list[dict] = []
        service._log_usage = lambda **kw: calls.append(kw)
        service._provider._fail = True
        service.chat([{"role": "user", "content": "hi"}], use_cache=False)
        assert calls and calls[0]["provider"] == "backup"


class TestSanitize:
    def test_hides_sk_key(self):
        out = sanitize("error: sk-abcdefgh1234567890 failed")
        assert "***" in out
        assert "sk-abcdefgh1234567890" not in out

    def test_hides_api_key(self):
        out = sanitize('headers {"api_key": "sk-test1234567890xyz"}')
        assert "***" in out
        assert "sk-test1234567890xyz" not in out

    def test_short_or_none_untouched(self):
        assert sanitize("") == ""
        assert sanitize("无敏感信息") == "无敏感信息"


class TestContextBuilder:
    def test_build_order(self):
        ctx = ContextBuilder().build(system_prompt="SYS", history=[{"role": "user", "content": "h1"}], user_input="q")
        assert [m["role"] for m in ctx.messages] == ["system", "user", "user"]
        assert ctx.messages[-1]["content"] == "q"

    def test_empty_parts_skipped(self):
        ctx = ContextBuilder().build(system_prompt="", history=[], user_input="")
        assert ctx.messages == []
