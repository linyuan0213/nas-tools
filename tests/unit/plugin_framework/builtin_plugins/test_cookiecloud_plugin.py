"""CookieCloud 插件 _verify_cookie 单元测试."""

from unittest.mock import MagicMock, patch

from app.plugin_framework.builtin_plugins.cookiecloud.backend.plugin import (
    CookieCloudPlugin,
)

MODULE = "app.plugin_framework.builtin_plugins.cookiecloud.backend.plugin"


def _make_plugin(site_def=None, test_result=(True, "ok", None)):
    ctx = MagicMock()
    ctx.site_engine.get_by_url.return_value = site_def
    ctx.site_engine.test_connection.return_value = test_result
    plugin = CookieCloudPlugin.__new__(CookieCloudPlugin)
    plugin.ctx = ctx
    return plugin


def _site_def(auth_type: str | None):
    api = MagicMock()
    api.auth = {"type": auth_type} if auth_type is not None else {}
    site_def = MagicMock()
    site_def.api = api
    return site_def


class TestVerifyCookieEnginePath:
    """cookie/csrf/无认证类型站点走引擎 test_connection 校验"""

    def test_cookie_auth_site_uses_test_connection(self):
        plugin = _make_plugin(site_def=_site_def("cookie"))
        assert plugin._verify_cookie("example.com", "uid=1; pass=2") is True
        plugin.ctx.site_engine.test_connection.assert_called_once()
        user_config = plugin.ctx.site_engine.test_connection.call_args[0][1]
        assert user_config["cookie"] == "uid=1; pass=2"
        assert user_config["api_key"] == ""

    def test_no_auth_site_uses_test_connection(self):
        plugin = _make_plugin(site_def=_site_def(None))
        assert plugin._verify_cookie("example.com", "uid=1") is True
        plugin.ctx.site_engine.test_connection.assert_called_once()

    def test_csrf_auth_site_uses_test_connection(self):
        plugin = _make_plugin(site_def=_site_def("csrf"))
        assert plugin._verify_cookie("example.com", "uid=1") is True
        plugin.ctx.site_engine.test_connection.assert_called_once()

    def test_test_connection_failure_returns_false(self):
        plugin = _make_plugin(site_def=_site_def("cookie"), test_result=(False, "登录失败", None))
        assert plugin._verify_cookie("example.com", "uid=1") is False


class TestVerifyCookieHtmlPath:
    """混合认证（api_key/bearer）站点 cookie 仅用于 HTML 页面，改走页面登录态校验"""

    def _run_html_check(self, plugin, logged_in=True, status_code=200):
        mock_res = MagicMock()
        mock_res.status_code = status_code
        mock_res.text = "<html></html>"
        with (
            patch(f"{MODULE}.HttpClient") as mock_client_cls,
            patch(f"{MODULE}.is_logged_in", return_value=logged_in) as mock_check,
        ):
            mock_client_cls.return_value.get.return_value = mock_res
            result = plugin._verify_cookie("www.hddolby.com", "c_secure_uid=1")
        return result, mock_client_cls, mock_check

    def test_api_key_site_uses_html_check(self):
        plugin = _make_plugin(site_def=_site_def("api_key"))
        result, mock_client_cls, mock_check = self._run_html_check(plugin)
        assert result is True
        plugin.ctx.site_engine.test_connection.assert_not_called()
        mock_check.assert_called_once()
        call_kwargs = mock_client_cls.return_value.get.call_args.kwargs
        assert call_kwargs["url"] == "https://www.hddolby.com"
        assert call_kwargs["auth"] is not None

    def test_bearer_site_uses_html_check(self):
        plugin = _make_plugin(site_def=_site_def("bearer"))
        result, _, _ = self._run_html_check(plugin)
        assert result is True
        plugin.ctx.site_engine.test_connection.assert_not_called()

    def test_api_key_site_not_logged_in_returns_false(self):
        plugin = _make_plugin(site_def=_site_def("api_key"))
        result, _, _ = self._run_html_check(plugin, logged_in=False)
        assert result is False

    def test_api_key_site_non_200_returns_false(self):
        plugin = _make_plugin(site_def=_site_def("api_key"))
        result, _, mock_check = self._run_html_check(plugin, status_code=403)
        assert result is False
        mock_check.assert_not_called()

    def test_no_site_def_uses_html_check(self):
        plugin = _make_plugin(site_def=None)
        result, _, _ = self._run_html_check(plugin)
        assert result is True

    def test_request_exception_returns_false(self):
        plugin = _make_plugin(site_def=_site_def("api_key"))
        with patch(f"{MODULE}.HttpClient") as mock_client_cls:
            mock_client_cls.return_value.get.side_effect = RuntimeError("网络异常")
            assert plugin._verify_cookie("www.hddolby.com", "uid=1") is False


class TestCookieCloudCommand:
    """CookieCloud 消息命令处理器测试（对齐 4 参数分发约定）"""

    def test_command_triggers_manual_sync_and_feedback(self):
        plugin = _make_plugin()
        plugin._cookie_sync = MagicMock()

        plugin._on_cookiecloud_cmd("/cookiecloud", "wx", "user1", "LinYuan")

        plugin._cookie_sync.assert_called_once_with(manual=True)
        plugin.ctx._message.send_channel_msg.assert_called_once()
        _, kwargs = plugin.ctx._message.send_channel_msg.call_args
        assert kwargs.get("channel") == "wx"
        assert kwargs.get("user_id") == "user1"
