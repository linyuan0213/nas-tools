"""Plugin framework 公开回调路由单元测试."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from api.routers import plugin_framework as plugin_router
from app.plugin_framework import api_registry


class TestPluginPublicWebhook:
    def _handler(self):
        return lambda params: {"code": 0, "msg": params.get("echo") or "success"}

    def _mock_request(self, body_bytes: bytes, query: dict | None = None):
        request = MagicMock()
        request.headers = {}
        request.query_params = query or {}

        async def _stream():
            for chunk in [body_bytes]:
                yield chunk

        request.stream = _stream
        return request

    def test_missing_handler_returns_error(self):
        response = asyncio.run(plugin_router.plugin_public_webhook("nonexistent", "cb", MagicMock()))
        assert "code" in bytes(response.body).decode()

    def test_dispatches_to_registered_handler_merges_query_and_body(self):
        handler = lambda params: {  # noqa: E731
            "code": 0,
            "apikey_ok": params.get("apikey") == "secret-key",
            "echo": params.get("echo") or "success",
        }
        api_registry.register_public_webhook("feishu", "callback", handler)
        try:
            request = self._mock_request(b'{"echo": "hi"}', {"apikey": "secret-key"})
            response = asyncio.run(plugin_router.plugin_public_webhook("feishu", "callback", request))
            body = bytes(response.body).decode()
            assert '"apikey_ok": true' in body
            assert '"hi"' in body
        finally:
            api_registry.unregister_plugin_all("feishu")

    def test_client_ip_not_spoofable(self):
        handler = lambda params: {  # noqa: E731
            "code": 0,
            "real_ip": params.get("_client_ip", ""),
        }
        api_registry.register_public_webhook("feishu", "cb_ip", handler)
        try:
            # body/query 中的 _client_ip 应被真实来源 IP 覆盖
            request = self._mock_request(b'{"_client_ip": "10.0.0.1"}', {"_client_ip": "10.0.0.2"})
            request.client = type("Client", (), {"host": "192.168.1.1"})()
            response = asyncio.run(plugin_router.plugin_public_webhook("feishu", "cb_ip", request))
            assert '"real_ip": "192.168.1.1"' in bytes(response.body).decode()
        finally:
            api_registry.unregister_plugin_all("feishu")

    def test_oversized_body_rejected(self):
        handler = self._handler()
        api_registry.register_public_webhook("feishu", "cb_big", handler)
        try:
            request = self._mock_request(b"x" * (plugin_router._MAX_CALLBACK_BODY + 1))
            response = asyncio.run(plugin_router.plugin_public_webhook("feishu", "cb_big", request))
            assert "请求体过大" in bytes(response.body).decode()
        finally:
            api_registry.unregister_plugin_all("feishu")

    def test_oversized_body_rejected_by_content_length(self):
        handler = self._handler()
        api_registry.register_public_webhook("feishu", "cb_len", handler)
        try:
            request = self._mock_request(b"{}")
            request.headers = {"content-length": str(plugin_router._MAX_CALLBACK_BODY + 1)}
            response = asyncio.run(plugin_router.plugin_public_webhook("feishu", "cb_len", request))
            assert "请求体过大" in bytes(response.body).decode()
        finally:
            api_registry.unregister_plugin_all("feishu")

    def test_unregister_removes_handler(self):
        api_registry.register_public_webhook("feishu", "cb2", self._handler())
        api_registry.unregister_plugin_all("feishu")
        assert api_registry.get_webhook_handler("feishu", "cb2") is None

    def test_handler_exception_returns_error_json(self):
        def boom(params):
            raise RuntimeError("boom")

        api_registry.register_public_webhook("feishu", "cb3", boom)
        try:
            request = MagicMock()
            request.body = AsyncMock(return_value=b"{}")
            request.query_params = {}
            response = asyncio.run(plugin_router.plugin_public_webhook("feishu", "cb3", request))
            assert "boom" in bytes(response.body).decode()
        finally:
            api_registry.unregister_plugin_all("feishu")
