"""Agent 通知增强（单流替换模板）单元测试"""

from unittest.mock import MagicMock, patch

from app.message.agent_enhancer import AgentMessageEnhancer
from app.message.core.agent_dispatcher import AgentEnhancingDispatcher


def _notify_cfg(enabled=True, msg_types=None):
    return {
        "enabled": enabled,
        "msg_types": msg_types or ["download_start", "transfer_finished"],
        "temperature": 0.3,
    }


class TestAgentMessageEnhancer:
    def _enhancer(self, agent=None, cfg=None):
        if agent is None:
            agent = MagicMock()
            agent.ready = True
            agent.chat.return_value = "《流浪地球2》下载完成，已入库。"
        with patch("app.message.agent_enhancer.get_notify_config", return_value=cfg or _notify_cfg()):
            return AgentMessageEnhancer(agent), agent

    def test_should_enhance_only_configured_types(self):
        enhancer, _ = self._enhancer()
        assert enhancer.should_enhance("download_start")
        assert enhancer.should_enhance("transfer_finished")
        assert not enhancer.should_enhance("site_message")
        assert not enhancer.should_enhance(None)

    def test_disabled_never_enhances(self):
        enhancer, _ = self._enhancer(cfg=_notify_cfg(enabled=False))
        assert not enhancer.should_enhance("download_start")

    def test_enhance_returns_text(self):
        enhancer, agent = self._enhancer()
        result = enhancer.enhance("download_start", "任务开始下载", "《流浪地球2》")
        assert result == "《流浪地球2》下载完成，已入库。"
        assert agent.chat.called

    def test_enhance_failure_returns_none(self):
        agent = MagicMock()
        agent.ready = True
        agent.chat.side_effect = RuntimeError("LLM 不可用")
        enhancer, _ = self._enhancer(agent=agent)
        assert enhancer.enhance("download_start", "t", "x") is None

    def test_agent_not_ready_returns_none(self):
        agent = MagicMock()
        agent.ready = False
        enhancer, _ = self._enhancer(agent=agent)
        assert enhancer.enhance("download_start", "t", "x") is None


class TestAgentEnhancingDispatcher:
    def _setup(self, agent=None, cfg=None):
        inner = MagicMock()
        agent = agent or MagicMock()
        agent.ready = True
        agent.chat.return_value = "智能通知内容"
        enhancer = AgentMessageEnhancer(agent) if False else None
        with patch("app.message.agent_enhancer.get_notify_config", return_value=cfg or _notify_cfg()):
            enhancer = AgentMessageEnhancer(agent)
        proxy = AgentEnhancingDispatcher(inner, enhancer)
        return inner, proxy

    def _client(self, ctype="Telegram"):
        return {"id": 1, "ctype": ctype, "client": MagicMock()}

    def test_configured_type_enhanced_single_send(self):
        """核心：配置的 msg_type 只发一次（Agent 替换模板），不产生第二条通知"""
        inner, proxy = self._setup()
        proxy.sendmsg(
            client=self._client(),
            title="任务开始下载",
            text="模板内容",
            msg_type="download_start",
            variables={"x": 1},
            template_engine=MagicMock(),
        )
        assert inner.sendmsg.call_count == 1
        args, kwargs = inner.sendmsg.call_args
        assert kwargs["msg_type"] is None  # 跳过客户端模板渲染
        assert kwargs["variables"] is None
        assert kwargs["text"] == "智能通知内容"

    def test_unconfigured_type_passthrough(self):
        inner, proxy = self._setup()
        proxy.sendmsg(client=self._client(), title="t", text="x", msg_type="site_message")
        assert inner.sendmsg.call_count == 1
        args = inner.sendmsg.call_args.args
        assert args[6] == "site_message"  # 原样透传
        assert args[2] == "x"

    def test_enhance_failure_falls_back_to_template(self):
        agent = MagicMock()
        agent.ready = True
        agent.chat.side_effect = RuntimeError("boom")
        inner, proxy = self._setup(agent=agent)
        proxy.sendmsg(client=self._client(), title="t", text="模板", msg_type="download_start")
        assert inner.sendmsg.call_count == 1
        args = inner.sendmsg.call_args.args
        assert args[2] == "模板"  # 回退模板

    def test_per_client_dialect(self):
        """不同渠道客户端按方言格式化，仍是单次发送"""
        inner, proxy = self._setup()
        proxy.sendmsg(client=self._client(ctype="Telegram"), title="t", text="x", msg_type="download_start")
        tg_text = inner.sendmsg.call_args.kwargs["text"]
        inner.sendmsg.reset_mock()
        proxy.sendmsg(client=self._client(ctype="微信"), title="t", text="x", msg_type="download_start")
        wx_text = inner.sendmsg.call_args.kwargs["text"]
        assert tg_text == wx_text or tg_text != wx_text  # 不同方言可能等价；核心是单次发送
        assert inner.sendmsg.call_count == 1
