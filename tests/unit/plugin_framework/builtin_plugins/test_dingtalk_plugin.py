"""钉钉消息插件测试：signer、事件解析、回调、发送."""

from unittest.mock import MagicMock, patch

from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.event_parser import parse_chatbot_message
from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.plugin import MsgDingtalkPlugin
from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.signer import gen_sign


class TestSigner:
    def test_gen_sign_deterministic(self):
        assert gen_sign("secret", 1700000000) == gen_sign("secret", 1700000000)

    def test_gen_sign_differs_by_timestamp(self):
        assert gen_sign("secret", 1700000000) != gen_sign("secret", 1700000001)


class TestEventParser:
    def test_parse_text_message(self):
        data = {
            "msgtype": "text",
            "text": {"content": "搜索 三体"},
            "senderStaffId": "staff123",
            "chatbotUserId": "$:LWCP_v1:$1",
        }
        user_id, text = parse_chatbot_message(data)
        assert user_id == "staff123"
        assert text == "搜索 三体"

    def test_parse_empty(self):
        assert parse_chatbot_message({}) == ("", "")

    def test_parse_non_text(self):
        assert parse_chatbot_message({"msgtype": "picture", "content": {}}) == ("", "")


class TestDingtalkPlugin:
    def _plugin(self):
        ctx = MagicMock()
        app_context = MagicMock()
        app_context.apikey_service.validate_key.return_value = MagicMock()
        message = MagicMock()
        return MsgDingtalkPlugin(ctx, app_context=app_context, message=message)

    def test_on_enable_registers_channel(self):
        plugin = self._plugin()
        plugin._message.get_interactive_client.return_value = {"client": None}
        with patch("app.plugin_framework.builtin_plugins.msg_dingtalk.backend.plugin.register") as mock_reg:
            plugin.on_enable()
            mock_reg.assert_called_once()
            plugin.ctx.register_public_webhook.assert_called_once()  # type: ignore[attr-defined]
            plugin._message.reload_by_type.assert_called_once_with("dingtalk")

    def test_callback_rejects_missing_apikey(self):
        plugin = self._plugin()
        result = plugin._on_callback({"user_id": "u1", "text": "搜索"})
        assert result["code"] == -1

    def test_callback_handles_message(self):
        plugin = self._plugin()
        with patch(
            "app.plugin_framework.builtin_plugins._msg_common.callback.get_message_command_handler"
        ) as mf:
            handler = MagicMock()
            mf.return_value = handler
            result = plugin._on_callback({"apikey": "k", "user_id": "staff1", "text": "搜索 三体"})
            assert result["code"] == 0
            handler.handle_message_job.assert_called_once_with(  # type: ignore[attr-defined]
                msg="搜索 三体", in_from="DINGTALK", user_id="staff1"
            )


class TestDingtalkClient:
    def _client(self, config: dict):
        from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client import DingTalk

        return DingTalk(config=config, apikey_service=MagicMock(), message=MagicMock())

    def test_send_msg_webhook(self):
        client = self._client({"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=x"})
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            mock_http.return_value.post.return_value = resp
            ok, err = client.send_msg(title="标题", text="正文")
            assert ok
            payload = mock_http.return_value.post.call_args[1]["json"]
            assert payload["msgtype"] == "markdown"
            assert payload["markdown"]["title"] == "标题"

    def test_send_msg_without_webhook(self):
        client = self._client({})
        ok, err = client.send_msg(title="标题")
        assert not ok
        assert "Webhook" in err

    def test_send_msg_signature_header(self):
        client = self._client({"webhook_url": "https://x/robot/send", "secret": "sec"})
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            mock_http.return_value.post.return_value = resp
            client.send_msg(title="标题")
            headers = mock_http.return_value.post.call_args[1]["headers"]
            assert "timestamp" in headers
            assert "sign" in headers

    def test_send_list_msg(self):
        media = MagicMock()
        media.get_title_string.return_value = "三体"
        client = self._client({"webhook_url": "https://x/robot/send"})
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            mock_http.return_value.post.return_value = resp
            ok, _ = client.send_list_msg([media], title="结果")
            assert ok
            payload = mock_http.return_value.post.call_args[1]["json"]
            assert "1." in payload["markdown"]["text"]

    def test_send_msg_uses_session_webhook_for_reply(self):
        client = self._client({})
        client.save_session_webhook("staff1", "https://oapi.dingtalk.com/robot/send?access_token=session")
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            mock_http.return_value.post.return_value = resp
            ok, _ = client.send_msg(title="回复", text="结果", user_id="staff1")
            assert ok
            url = mock_http.return_value.post.call_args[0][0]
            assert "session" in url

    def test_send_msg_fallback_to_webhook_without_session(self):
        client = self._client({"webhook_url": "https://x/robot/send"})
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            mock_http.return_value.post.return_value = resp
            ok, _ = client.send_msg(title="通知", user_id="staff1")
            assert ok
            url = mock_http.return_value.post.call_args[0][0]
            assert "x/robot/send" in url

    def test_send_msg_uses_corp_conversation(self):
        client = self._client(
            {"app_key": "ding_k", "app_secret": "sec", "agent_id": "123456", "default_user_ids": "user1"}
        )
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            def _fake_post(url, **kw):
                resp = MagicMock()
                if "oauth2/accessToken" in str(url):
                    resp.json.return_value = {"accessToken": "tok", "expireIn": 7200}
                elif "batchSend" in str(url):
                    resp.json.return_value = {"processQueryKey": "ok"}
                return resp

            mock_http.return_value.post.side_effect = _fake_post
            ok, _ = client.send_msg(title="通知", text="下载完成")
            assert ok
            post_calls = mock_http.return_value.post.call_args_list
            batch = [c for c in post_calls if "batchSend" in str(c[0][0])]
            assert batch
            body = batch[0][1]["json"]
            assert body["msgKey"] == "sampleMarkdown"
            assert "user1" in body["userIds"]

    def test_send_msg_corp_conversation_fallback_webhook(self):
        client = self._client(
            {
                "app_key": "ding_k",
                "app_secret": "sec",
                "agent_id": "123456",
                "webhook_url": "https://x/robot/send",
            }
        )
        with patch(
            "app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client.HttpClient"
        ) as mock_http:
            def _fake_post(url, **kw):
                resp = MagicMock()
                if "oauth2/accessToken" in str(url):
                    resp.json.return_value = {"accessToken": "tok", "expireIn": 7200}
                elif "batchSend" in str(url):
                    resp.json.return_value = {"code": "error", "message": "失败"}
                else:
                    resp.json.return_value = {"errcode": 0}  # 群 Webhook 成功
                return resp

            mock_http.return_value.post.side_effect = _fake_post
            ok, _ = client.send_msg(title="通知")
            assert ok  # 回退到群 Webhook 成功
