"""浏览器自动化相关单元测试."""

from unittest.mock import patch

from lxml import etree

from app.infrastructure.http.config import BrowserModeConfig, HttpClientConfig
from app.utils.browser_mode import build_browser_mode, get_chrome_server_url
from app.utils.render_normalize import normalize_rendered_html


def test_browser_mode_config_defaults():
    browser = BrowserModeConfig()
    assert not browser.enabled
    assert browser.fingerprint_profile == "stealth"
    assert browser.render_html is False


def test_http_client_config_accepts_browser():
    browser = BrowserModeConfig(enabled=True, server_url="http://localhost:9850")
    config = HttpClientConfig(browser=browser)
    assert config.browser is browser


def test_normalize_rendered_html_strips_tbody():
    html = "<table><tbody><tr><td>1</td></tr></tbody></table>"
    normalized = normalize_rendered_html(html)
    doc = etree.HTML(f"<body>{normalized}</body>")
    assert doc.xpath("//tbody") == []
    assert doc.xpath("//tr") != []


def test_normalize_rendered_html_no_tbody_passthrough():
    html = "<div><span>text</span></div>"
    normalized = normalize_rendered_html(html)
    assert "<span>text</span>" in normalized


def test_build_browser_mode_disabled_when_site_flag_off():
    assert build_browser_mode({"chrome": False}, "pt") is None


def test_build_browser_mode_enabled():
    browser = build_browser_mode({"chrome": True, "ua": "test-ua"}, "pt", server_url="http://chrome:9850")
    assert browser is not None
    assert browser.enabled is True
    assert browser.server_url == "http://chrome:9850"
    assert browser.user_agent == "test-ua"
    assert browser.session_key.startswith("pt:")


def test_build_browser_mode_render_html_override():
    browser = build_browser_mode({"chrome": True}, "pt", server_url="http://chrome:9850", render_html=True)
    assert browser is not None
    assert browser.render_html is True


def test_get_chrome_server_url_disabled():
    with patch("app.utils.browser_mode.settings") as mock_settings:
        mock_settings.get.return_value = {
            "chrome_enabled": False,
            "chrome_server_host": "http://chrome:9850",
        }
        assert get_chrome_server_url() is None


def test_get_chrome_server_url_enabled():
    with patch("app.utils.browser_mode.settings") as mock_settings:
        mock_settings.get.return_value = {
            "chrome_enabled": True,
            "chrome_server_host": "http://chrome:9850",
        }
        assert get_chrome_server_url() == "http://chrome:9850"


def test_build_browser_mode_disabled_globally():
    with patch("app.utils.browser_mode.settings") as mock_settings:
        mock_settings.get.return_value = {
            "chrome_enabled": False,
            "chrome_server_host": "http://chrome:9850",
        }
        assert build_browser_mode({"chrome": True}, "pt") is None


def test_browser_mode_config_api_key_default_none():
    """api_key 默认空（nexus-chrome 本地模式不需要凭证）。"""
    assert BrowserModeConfig().api_key is None


def test_build_browser_mode_includes_api_key():
    """站点配置构造时携带全局凭证（laboratory.chrome_admin_token）。"""
    with patch("app.utils.browser_mode.settings") as mock_settings:
        mock_settings.get.return_value = {
            "chrome_enabled": True,
            "chrome_server_host": "http://chrome:9850",
            "chrome_admin_token": "ncmk_test123",
        }
        browser = build_browser_mode({"chrome": True}, "pt")
    assert browser is not None
    assert browser.api_key == "ncmk_test123"


def test_chrome_server_client_sends_auth_header():
    """_ChromeServerClient 配置 api_key 后所有请求携带 Bearer 头。"""
    from app.infrastructure.http.browser_transport import _ChromeServerClient

    client = _ChromeServerClient("http://chrome:9850", api_key="ncmk_test123")
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs.get("headers") or {})
        return _Resp()

    with patch.object(client._client, "request", side_effect=fake_request):
        client._request("GET", "/sessions")
    assert captured.get("Authorization") == "Bearer ncmk_test123"


def test_chrome_server_client_no_key_no_header():
    """未配置 api_key 时不携带认证头。"""
    from app.infrastructure.http.browser_transport import _ChromeServerClient

    client = _ChromeServerClient("http://chrome:9850")
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 0}

    with patch.object(
        client._client,
        "request",
        side_effect=lambda method, url, **kw: captured.update(kw.get("headers") or {}) or _Resp(),
    ):
        client._request("GET", "/sessions")
    assert "Authorization" not in captured


def test_browser_session_auth_headers():
    """BrowserSession 显式 api_key 优先；未传时读全局配置。"""
    from app.infrastructure.chrome.session import BrowserSession

    s = BrowserSession("pt", server_url="http://chrome:9850", api_key="k1")
    assert s._auth_headers() == {"Authorization": "Bearer k1"}

    with patch(
        "app.infrastructure.chrome.session.get_chrome_api_key",
        return_value="ncmk_global",
    ):
        s2 = BrowserSession("pt", server_url="http://chrome:9850")
        assert s2._auth_headers() == {"Authorization": "Bearer ncmk_global"}
