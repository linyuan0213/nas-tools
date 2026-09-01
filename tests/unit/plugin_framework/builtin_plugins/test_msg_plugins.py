"""消息渠道插件（msg_*）基础测试：manifest 解析、生命周期、交互回调."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("slack_bolt")

from app.message import registry as msg_registry
from app.plugin_framework.builtin_plugins.msg_slack.backend.event_parser import parse_event as slack_parse
from app.plugin_framework.builtin_plugins.msg_slack.backend.plugin import MsgSlackPlugin
from app.plugin_framework.builtin_plugins.msg_synologychat.backend.event_parser import parse_event as syno_parse
from app.plugin_framework.builtin_plugins.msg_synologychat.backend.plugin import MsgSynologychatPlugin

BASE = "src/app/plugin_framework/builtin_plugins"
MSG_PLUGINS = ["msg_bark", "msg_chanify", "msg_gotify", "msg_iyuu", "msg_ntfy",
               "msg_pushdeer", "msg_pushplus", "msg_serverchan", "msg_slack",
               "msg_synologychat", "msg_webhook"]


class TestMsgPluginManifest:
    def test_all_msg_plugins_have_valid_manifest(self):
        for pid in MSG_PLUGINS:
            path = os.path.join(BASE, pid, "manifest.json")
            assert os.path.exists(path), f"{pid} 缺少 manifest"
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
            assert m["id"] == pid
            assert m["backend"]["entry"].startswith("backend.plugin:")


class TestMsgBarkLifecycle:
    def test_on_enable_registers_channel(self):
        from app.plugin_framework.builtin_plugins.msg_bark.backend.plugin import MsgBarkPlugin

        plugin = MsgBarkPlugin(MagicMock(), message=MagicMock())
        with patch("app.plugin_framework.builtin_plugins.msg_bark.backend.plugin.register") as mock_reg:
            plugin.on_enable()
            mock_reg.assert_called_once()
            plugin._message.reload_by_type.assert_called_once_with("bark")

    def test_on_disable_unregisters(self):
        from app.plugin_framework.builtin_plugins.msg_bark.backend.plugin import MsgBarkPlugin

        plugin = MsgBarkPlugin(MagicMock(), message=MagicMock())
        with (
            patch("app.plugin_framework.builtin_plugins.msg_bark.backend.plugin.unregister") as mock_unreg,
            patch(
                "app.plugin_framework.builtin_plugins.msg_bark.backend.plugin.disable_channel_record"
            ) as mock_disable,
        ):
            plugin.on_disable()
            mock_unreg.assert_called_once_with("bark")
            mock_disable.assert_called_once_with(plugin._message, "bark")


class TestSlackPlugin:
    def _plugin(self):
        ctx = MagicMock()
        app_context = MagicMock()
        app_context.apikey_service.validate_key.return_value = MagicMock()
        message = MagicMock()
        return MsgSlackPlugin(ctx, app_context=app_context, message=message)

    def test_on_enable_registers_webhook(self):
        plugin = self._plugin()
        plugin._message.get_interactive_client.return_value = {"client": None}
        with patch("app.plugin_framework.builtin_plugins.msg_slack.backend.plugin.register"):
            plugin.on_enable()
            plugin.ctx.register_public_webhook.assert_called_once()  # type: ignore[attr-defined]
            plugin._message.reload_by_type.assert_called_once_with("slack")

    def test_callback_rejects_missing_apikey(self):
        plugin = self._plugin()
        result = plugin._on_callback({"text": "搜索"})
        assert result["code"] == -1

    def test_callback_url_verification(self):
        plugin = self._plugin()
        result = plugin._on_callback({"apikey": "k", "type": "url_verification", "challenge": "abc"})
        assert result["challenge"] == "abc"

    def test_callback_handles_message(self):
        plugin = self._plugin()
        plugin._message.get_interactive_client.return_value = {"client": None}
        with patch("app.plugin_framework.builtin_plugins._msg_common.callback.get_message_command_handler") as mf:
            handler = MagicMock()
            mf.return_value = handler
            result = plugin._on_callback(
                {"apikey": "k", "_client_ip": "127.0.0.1", "user": "U123", "text": "搜索 三体"}
            )
            assert result["code"] == 0
            handler.handle_message_job.assert_called_once_with(  # type: ignore[attr-defined]
                msg="搜索 三体", in_from="SLACK", user_id="U123"
            )

    def test_event_parser(self):
        assert slack_parse({"user": "U1", "text": "你好"}) == ("U1", "你好")
        assert slack_parse({"user": {"id": "U2"}, "command": "/cmd"}) == ("U2", "/cmd")
        assert slack_parse({}) == ("", "")


class TestSynologyChatPlugin:
    def _plugin(self):
        ctx = MagicMock()
        app_context = MagicMock()
        app_context.apikey_service.validate_key.return_value = MagicMock()
        message = MagicMock()
        return MsgSynologychatPlugin(ctx, app_context=app_context, message=message)

    def test_callback_handles_message(self):
        plugin = self._plugin()
        plugin._message.get_interactive_client.return_value = {"client": None}
        with patch(
            "app.plugin_framework.builtin_plugins._msg_common.callback.get_message_command_handler"
        ) as mf:
            handler = MagicMock()
            mf.return_value = handler
            result = plugin._on_callback(
                {"apikey": "k", "_client_ip": "127.0.0.1", "user_id": "5", "text": "订阅 三体"}
            )
            assert result["code"] == 0
            handler.handle_message_job.assert_called_once_with(  # type: ignore[attr-defined]
                msg="订阅 三体", in_from="SYNOLOGY", user_id="5"
            )

    def test_event_parser(self):
        assert syno_parse({"user_id": "5", "text": "你好"}) == ("5", "你好")
        assert syno_parse({}) == ("", "")


class TestChannelUnregistration:
    def test_unregistered_types_not_in_registry(self):
        # 插件化渠道在未加载插件时不应注册
        for ctype in ["bark", "slack", "pushplus", "serverchan", "webhook"]:
            msg_registry.unregister(ctype)
        for ctype in ["bark", "slack", "pushplus", "serverchan", "webhook"]:
            assert msg_registry.get_client_class(ctype) is None

    def test_web_message_kept_in_registry(self):
        # 内置消息页渠道类由核心注册
        from app.message.client.web import WebMessage

        assert msg_registry.get_client_class("web") is WebMessage
