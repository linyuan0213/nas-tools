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
