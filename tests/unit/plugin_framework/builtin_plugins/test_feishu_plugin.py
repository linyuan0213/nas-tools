"""飞书插件单元测试：签名、事件解析、公开回调."""

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("lark_oapi")

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

from app.plugin_framework.builtin_plugins.feishu.backend.event_parser import (
    parse_card_action,
    parse_im_message,
)
from app.plugin_framework.builtin_plugins.feishu.backend.plugin import FeishuPlugin
from app.plugin_framework.builtin_plugins.feishu.backend.signer import gen_sign


class TestSigner:
    def test_gen_sign_deterministic(self):
        assert gen_sign("secret", 1700000000) == gen_sign("secret", 1700000000)

    def test_gen_sign_differs_by_timestamp(self):
        assert gen_sign("secret", 1700000000) != gen_sign("secret", 1700000001)

    def test_gen_sign_is_base64(self):
        import base64

        base64.b64decode(gen_sign("secret", 1700000000))


class TestEventParser:
    def _im_event(self, content: str, open_id: str = "ou_123"):
        raw = {
            "schema": "2.0",
            "header": {
                "event_id": "e1",
                "event_type": "im.message.receive_v1",
                "create_time": "1",
                "app_id": "cli_x",
                "tenant_key": "t",
            },
            "event": {
                "sender": {"sender_id": {"open_id": open_id}},
                "message": {"message_id": "om_x", "msg_type": "text", "content": content},
                "token": "x",
            },
            "type": "event",
        }
        return P2ImMessageReceiveV1(json.loads(json.dumps(raw)))

    def _card_event(self, value, open_id: str = "ou_456"):
        raw = {
            "schema": "2.0",
            "event": {
                "type": "card.action.trigger",
                "action": {"value": value, "tag": "button"},
                "operator": {"open_id": open_id, "union_id": "", "user_id": ""},
                "context": {"open_message_id": "om_x"},
                "host": {"tenant_key": "t", "app_id": "cli_x"},
                "request_id": "r1",
            },
        }
        return P2CardActionTrigger(json.loads(json.dumps(raw)))

    def test_parse_receive_v1(self):
        user_id, text = parse_im_message(self._im_event('{"text":"搜索 三体"}'))
        assert user_id == "ou_123"
        assert text == "搜索 三体"

    def test_parse_receive_v1_invalid_content(self):
        user_id, text = parse_im_message(self._im_event("not-json"))
        assert user_id == "ou_123"
        assert text == ""

    def test_parse_card_action_trigger(self):
        user_id, text = parse_card_action(self._card_event({"value": "3"}))
        assert user_id == "ou_456"
        assert text == "3"

    def test_parse_card_action_without_text_key(self):
        user_id, text = parse_card_action(self._card_event({"key": "x"}))
        assert user_id == "ou_456"
        assert text == ""

    def test_parse_empty_event(self):
        assert parse_im_message(P2ImMessageReceiveV1()) == ("", "")
        assert parse_card_action(P2CardActionTrigger()) == ("", "")


class TestFeishuPluginCallback:
    def _plugin(self):
        ctx = MagicMock()
        ctx.plugin_id = "feishu"
        app_context = MagicMock()
        app_context.apikey_service.validate_key.return_value = MagicMock()
        message = MagicMock()
        return FeishuPlugin(ctx, app_context=app_context, message=message)

    def test_on_enable_registers_channel_class(self):
        plugin = self._plugin()
        with patch("app.plugin_framework.builtin_plugins.feishu.backend.plugin.register") as mock_reg:
            plugin.on_enable()
            mock_reg.assert_called_once()

    def test_callback_rejects_missing_apikey(self):
        plugin = self._plugin()
        result = plugin._on_callback({"user_id": "ou_1", "text": "搜索"})
        assert result["code"] == -1

    def test_callback_rejects_invalid_apikey(self):
        plugin = self._plugin()
        plugin._app_context.apikey_service.validate_key.return_value = None
        result = plugin._on_callback({"apikey": "bad", "user_id": "ou_1", "text": "搜索"})
        assert result["code"] == -1

    def test_callback_handles_message(self):
        plugin = self._plugin()
        with patch(
            "app.plugin_framework.builtin_plugins._msg_common.callback.get_message_command_handler"
        ) as mock_factory:
            handler = MagicMock()
            mock_factory.return_value = handler
            result = plugin._on_callback({"apikey": "valid", "user_id": "ou_123", "text": "搜索 三体"})
            assert result["code"] == 0
            mock_factory.assert_called_once_with(plugin._app_context, plugin._message)
            handler.handle_message_job.assert_called_once_with(msg="搜索 三体", in_from="FEISHU", user_id="ou_123")

    def test_callback_ignores_empty_text(self):
        plugin = self._plugin()
        with patch(
            "app.plugin_framework.builtin_plugins._msg_common.callback.get_message_command_handler"
        ) as mock_factory:
            result = plugin._on_callback({"apikey": "valid", "user_id": "ou_1", "text": ""})
            assert result["code"] == 0
            mock_factory.assert_not_called()
