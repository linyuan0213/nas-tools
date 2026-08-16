"""Telegram 客户端 send_msg HTML 转义测试（修复文件名/番号特殊字符触发 400）."""

from unittest.mock import MagicMock, patch

from app.message.client.telegram import Telegram


class TestTelegramSendMsgHtml:
    def _client(self):
        client = Telegram.__new__(Telegram)
        client.token = "bot:token"
        client.chat_id = "12345"
        client._enabled = True
        client.interactive = False
        client._user_ids = []
        client._webhook_url = None
        client._proxy_event = None
        return client

    def test_parse_mode_html_and_escaped_caption(self):
        """标题加粗用 <b>，内容转义，parse_mode=HTML"""
        client = self._client()
        with patch("app.message.client.telegram.HttpClient") as mock_http:
            mock_res = MagicMock()
            mock_res.json.return_value = {"ok": True}
            mock_http.return_value.post.return_value = mock_res
            ok, msg = client.send_msg(title="SSNI-209 下载完成", text="路径含 _下划线_ [括号] ~字符# 和 & 符号")
            assert ok
            _, kwargs = mock_http.return_value.post.call_args
            data = kwargs.get("data") or mock_http.return_value.post.call_args[0][1]
            assert data["parse_mode"] == "HTML"
            caption = data["text"]
            # 标题加粗，内容特殊字符被 HTML 转义（不会触发 Telegram Markdown 400）
            assert "<b>SSNI-209 下载完成</b>" in caption
            assert "&amp;" in caption
            assert "_下划线_" in caption  # 下划线不再作为 markdown 解析，原样保留

    def test_image_caption_html(self):
        client = self._client()
        with patch("app.message.client.telegram.HttpClient") as mock_http:
            mock_res = MagicMock()
            mock_res.json.return_value = {"ok": True}
            mock_http.return_value.post.return_value = mock_res
            ok, msg = client.send_msg(title="剧集", text="S01E05 [1080p]", image="https://img/x.jpg")
            assert ok
            url = mock_http.return_value.post.call_args[0][0]
            assert "sendPhoto" in url
            data = mock_http.return_value.post.call_args.kwargs["data"]
            assert data["parse_mode"] == "HTML"
            assert "<b>剧集</b>" in data["caption"]
