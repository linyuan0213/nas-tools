"""Feishu 消息渠道客户端单元测试."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("lark_oapi")

from app.plugin_framework.builtin_plugins.feishu.backend.message_client import (
    Feishu,
    build_card,
    build_list_card,
    build_webhook_payload,
)


class TestFeishuCardBuilders:
    def test_build_webhook_payload(self):
        payload = build_webhook_payload("标题", "正文", "")
        assert payload["msg_type"] == "text"
        assert payload["content"]["text"] == "标题\n正文"

    def test_build_webhook_payload_without_text(self):
        payload = build_webhook_payload("仅标题", "", "")
        assert payload["content"]["text"] == "仅标题"

    def test_build_card_with_url_button(self):
        card = build_card("标题", "正文", "https://example.com/detail")
        assert card["header"]["title"]["content"] == "标题"
        divs = [e for e in card["elements"] if e["tag"] == "div"]
        assert divs[0]["text"]["content"] == "正文"
        actions = [e for e in card["elements"] if e["tag"] == "action"]
        assert actions and actions[0]["actions"][0]["url"] == "https://example.com/detail"

    def test_build_card_title_not_repeated_in_body(self):
        card = build_card("开始下载 进击的巨人", "正在下载 S01 全季", "")
        divs = [e for e in card["elements"] if e["tag"] == "div"]
        assert divs[0]["text"]["content"] == "正在下载 S01 全季"
        assert "开始下载 进击的巨人" not in divs[0]["text"]["content"]

    def test_build_card_body_falls_back_to_title(self):
        card = build_card("仅标题", "", "")
        divs = [e for e in card["elements"] if e["tag"] == "div"]
        assert divs[0]["text"]["content"] == "仅标题"

    def test_build_card_with_img_key(self):
        card = build_card("标题", "正文", "", img_key="img_v2_x")
        imgs = [e for e in card["elements"] if e["tag"] == "img"]
        assert imgs and imgs[0]["img_key"] == "img_v2_x"

    def test_build_list_card(self):
        media = MagicMock()
        media.get_title_string.return_value = "进击的巨人"
        media.get_star_string.return_value = "9.5"
        media.get_overview_string.return_value = "简介"
        media.get_type_string.return_value = "电视剧"
        card = build_list_card([media], "搜索结果")
        assert card["header"]["title"]["content"] == "搜索结果"
        buttons = [e for e in card["elements"] if e["tag"] == "action"]
        assert len(buttons) == 1
        assert buttons[0]["actions"][0]["value"] == {"value": "1"}


class TestFeishuClient:
    def _client(self, config: dict):
        return Feishu(config=config, apikey_service=MagicMock(), message=MagicMock())

    def test_mode_detection_webhook_only(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/xxx"})
        assert client._mode == "webhook"

    def test_mode_detection_app_only(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret"})
        assert client._mode == "app"

    def test_mode_detection_app_preferred_when_both(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/xxx", "app_id": "cli_1", "app_secret": "secret"})
        assert client._mode == "app"

    def test_mode_detection_no_config_defaults_app(self):
        client = self._client({})
        assert client._mode == "app"

    def test_send_msg_webhook_mode(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/hook/abc"})
        with patch(
            "app.plugin_framework.builtin_plugins.feishu.backend.message_client.FeishuApi.send_webhook",
            return_value=(True, ""),
        ) as mock_send:
            ok, msg = client.send_msg(title="标题", text="正文")
            assert ok
            assert msg == ""
            payload, kwargs = mock_send.call_args
            assert payload[0]["msg_type"] == "text"

    def test_send_msg_app_mode_uses_user_id_first(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret", "default_receivers": "ou_default"})
        with patch(
            "app.plugin_framework.builtin_plugins.feishu.backend.message_client.FeishuApi.send_card",
            return_value=(True, ""),
        ) as mock_send:
            ok, _ = client.send_msg(title="标题", user_id="ou_reply")
            assert ok
            assert mock_send.call_args[0][0] == "ou_reply"

    def test_send_msg_app_mode_no_receiver(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret"})
        ok, msg = client.send_msg(title="标题")
        assert not ok
        assert "接收人" in msg

    def test_send_list_msg_webhook_not_supported(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/hook/abc"})
        ok, msg = client.send_list_msg([MagicMock()], user_id="ou_1")
        assert not ok
        assert "Webhook 模式" in msg

    def test_send_list_msg_app_mode(self):
        media = MagicMock()
        media.get_title_string.return_value = "三体"
        client = self._client({"app_id": "cli_1", "app_secret": "secret", "default_receivers": "ou_x"})
        with patch(
            "app.plugin_framework.builtin_plugins.feishu.backend.message_client.FeishuApi.send_card",
            return_value=(True, ""),
        ) as mock_send:
            ok, _ = client.send_list_msg([media], user_id="ou_1", title="结果")
            assert ok
            card = mock_send.call_args[0][1]
            assert card["header"]["title"]["content"] == "结果"

    def test_send_msg_app_mode_with_image(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret", "default_receivers": "ou_x"})
        with (
            patch.object(client, "_resolve_image", return_value="img_v2_x") as mock_resolve,
            patch(
                "app.plugin_framework.builtin_plugins.feishu.backend.message_client.FeishuApi.send_card",
                return_value=(True, ""),
            ) as mock_send,
        ):
            ok, _ = client.send_msg(title="标题", image="https://example.com/poster.jpg", user_id="ou_1")
            assert ok
            mock_resolve.assert_called_once_with("https://example.com/poster.jpg")
            card = mock_send.call_args[0][1]
            assert card["elements"][0]["tag"] == "img"
            assert card["elements"][0]["img_key"] == "img_v2_x"

    def test_resolve_image_failure_falls_back_to_no_image(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret", "default_receivers": "ou_x"})
        with (
            patch(
                "app.plugin_framework.builtin_plugins.feishu.backend.message_client.HttpClient",
                side_effect=RuntimeError("网络错误"),
            ),
            patch(
                "app.plugin_framework.builtin_plugins.feishu.backend.message_client.FeishuApi.send_card",
                return_value=(True, ""),
            ) as mock_send,
        ):
            ok, _ = client.send_msg(title="标题", image="https://example.com/poster.jpg", user_id="ou_1")
            assert ok
            card = mock_send.call_args[0][1]
            assert all(e["tag"] != "img" for e in card["elements"])

    def test_get_status_app_mode_validates_token(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret"})
        with patch.object(client._feishu_api, "get_tenant_access_token", return_value="token"):
            assert client.get_status() is True

    def test_get_status_app_mode_sends_message_with_receiver(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret", "default_receivers": "ou_x"})
        with (
            patch.object(client._feishu_api, "get_tenant_access_token", return_value="token"),
            patch.object(client._feishu_api, "send_card", return_value=(True, "")) as mock_send,
        ):
            assert client.get_status() is True
            mock_send.assert_called_once()

    def test_get_status_app_mode_missing_credentials(self):
        client = self._client({"app_id": "", "app_secret": ""})
        assert client.get_status() is False

    def test_get_status_app_mode_token_error(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret"})
        with patch.object(client._feishu_api, "get_tenant_access_token", side_effect=RuntimeError("无效凭证")):
            assert client.get_status() is False

    def test_get_status_webhook_mode_sends(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/hook/abc"})
        with patch.object(client._feishu_api, "send_webhook", return_value=(True, "")):
            assert client.get_status() is True

    def test_setup_skips_in_webhook_mode(self):
        client = self._client({"webhook_url": "https://open.feishu.cn/hook/abc"})
        with patch("app.plugin_framework.builtin_plugins.feishu.backend.message_client.WsServer") as mock_ws:
            client.setup()
            mock_ws.assert_not_called()

    def test_setup_skips_without_app_secret(self):
        client = self._client({"app_id": "cli_1"})
        with patch("app.plugin_framework.builtin_plugins.feishu.backend.message_client.WsServer") as mock_ws:
            client.setup()
            mock_ws.assert_not_called()

    def test_setup_starts_ws_in_app_mode(self):
        client = self._client({"app_id": "cli_1", "app_secret": "secret"})
        with patch("app.plugin_framework.builtin_plugins.feishu.backend.message_client.WsServer") as mock_ws:
            client.setup()
            mock_ws.assert_called_once()
            mock_ws.return_value.start.assert_called_once()
