"""浏览器降级请求完成后关闭会话的回归测试.

防止 nexus-chrome 会话/标签页在进程退出前持续堆积：
engine / html_searcher / config_html 三处"直连优先→chrome 降级"调用点，
浏览器模式请求必须用完即 release（触发非持久会话删除）。
"""

import contextlib
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.infrastructure.http.config import BrowserModeConfig, HttpClientConfig
from app.sites.engine import SiteEngine
from app.sites.html_searcher import HtmlSiteSearcher
from app.sites.siteuserinfo.config_html import ConfigHtmlUserInfo


class _Resp:
    def __init__(self, is_success: bool, status_code: int, text: str):
        self.is_success = is_success
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


def _make_fake_http_client(responses):
    """按实例创建顺序返回响应列表对应元素的假 HttpClient."""

    instances = []

    class FakeHttpClient:
        def __init__(self, config=None, rate_limiter=None):
            self.config = config or HttpClientConfig()
            self.rate_limiter = rate_limiter
            self.closed = False
            self._idx = len(instances)
            instances.append(self)

        def get(self, url, **kwargs):
            return responses[self._idx]

        def close(self):
            self.closed = True

    return FakeHttpClient, instances


def _browser_mode(site_key: str) -> BrowserModeConfig:
    return BrowserModeConfig(
        enabled=True,
        server_url="http://chrome:9850",
        session_key=site_key,
        site_key=site_key,
        render_html=True,
    )


def _patch_http_client(module_name: str, fake_http, browser_mode: BrowserModeConfig):
    """直连失败(403) -> 浏览器降级路径所需的模块级桩补丁（context manager）."""
    patchers = [
        patch(f"{module_name}.HttpClient", fake_http),
        patch(f"{module_name}.build_browser_mode", return_value=browser_mode),
        patch("app.sites.engine_tools._get_rate_limit_kwargs", return_value={}),
    ]

    @contextlib.contextmanager
    def _manager():
        with ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            yield

    return _manager()


def _assert_browser_client_released(instances, browser_mode):
    assert len(instances) == 2
    assert instances[0].config.browser is None
    browser_client = instances[1]
    assert browser_client.config.browser is browser_mode
    assert browser_client.closed is True


class TestEngineFetchPageFallback:
    def test_browser_fallback_client_is_closed(self):
        responses = [_Resp(False, 403, ""), _Resp(True, 200, "chrome-page")]
        fake_http, instances = _make_fake_http_client(responses)
        engine: Any = SiteEngine.__new__(SiteEngine)
        engine.site_limiter = None
        engine.get_by_url = lambda url: SimpleNamespace(api=None, id="site-x")
        browser_mode = _browser_mode("site-x")
        with _patch_http_client("app.sites.engine", fake_http, browser_mode):
            text = engine._fetch_page(
                "http://pt.example.com/detail/1",
                {"chrome": True, "ua": "u", "cookie": ""},
            )
        assert text == "chrome-page"
        _assert_browser_client_released(instances, browser_mode)

    def test_direct_success_skips_browser(self):
        responses = [_Resp(True, 200, "normal-page")]
        fake_http, instances = _make_fake_http_client(responses)
        engine: Any = SiteEngine.__new__(SiteEngine)
        engine.site_limiter = None
        engine.get_by_url = lambda url: SimpleNamespace(api=None, id="site-x")
        with _patch_http_client("app.sites.engine", fake_http, _browser_mode("site-x")):
            text = engine._fetch_page(
                "http://pt.example.com/detail/1",
                {"chrome": True, "ua": "u", "cookie": ""},
            )
        assert text == "normal-page"
        assert len(instances) == 1
        assert instances[0].config.browser is None

    def test_browser_fallback_forwards_persistent_flag(self):
        responses = [_Resp(False, 403, ""), _Resp(True, 200, "chrome-page")]
        fake_http, _ = _make_fake_http_client(responses)
        engine: Any = SiteEngine.__new__(SiteEngine)
        engine.site_limiter = None
        engine.get_by_url = lambda url: SimpleNamespace(api=None, id="site-x")
        captured = {}

        def fake_build_browser_mode(site_info, **kwargs):
            captured["site_info"] = site_info
            return _browser_mode("site-x")

        with (
            patch("app.sites.engine.HttpClient", fake_http),
            patch("app.sites.engine.build_browser_mode", side_effect=fake_build_browser_mode),
            patch("app.sites.engine_tools._get_rate_limit_kwargs", return_value={}),
        ):
            text = engine._fetch_page(
                "http://pt.example.com/detail/1",
                {"chrome": True, "ua": "u", "cookie": "", "browser_persistent": True},
            )
        assert text == "chrome-page"
        assert captured["site_info"].get("browser_persistent") is True


class TestHtmlSearcherFallback:
    def test_browser_fallback_client_is_closed(self):
        responses = [_Resp(False, 403, ""), _Resp(True, 200, "chrome-list")]
        fake_http, instances = _make_fake_http_client(responses)
        searcher: Any = HtmlSiteSearcher.__new__(HtmlSiteSearcher)
        searcher._site = SimpleNamespace(domain="pt.example.com", name="PT", encoding=None)
        searcher._user_config = {"chrome": True, "ua": "u", "domain": "pt.example.com", "cookie": ""}
        searcher._site_engine = SimpleNamespace()
        browser_mode = _browser_mode("pt.example.com")
        with _patch_http_client("app.sites.html_searcher", fake_http, browser_mode):
            html = searcher._fetch_html("http://pt.example.com/browse/xxx")
        assert html == "chrome-list"
        _assert_browser_client_released(instances, browser_mode)


class TestConfigHtmlFallback:
    def test_browser_fallback_client_is_closed(self):
        responses = [_Resp(False, 403, ""), _Resp(True, 200, "chrome-html")]
        fake_http, instances = _make_fake_http_client(responses)
        cfg: Any = ConfigHtmlUserInfo.__new__(ConfigHtmlUserInfo)
        cfg._headers = None
        cfg._ua = "u"
        cfg._base_url_str = "http://pt.example.com"
        cfg._proxies = None
        cfg._site_engine = SimpleNamespace()
        cfg._def = SimpleNamespace(id="def-1")
        cfg._cookie = ""
        cfg.site_name = "PT"
        cfg._emulate = True
        browser_mode = _browser_mode("def-1")
        with _patch_http_client("app.sites.siteuserinfo.config_html", fake_http, browser_mode):
            text = cfg._fetch_html("http://pt.example.com/usercp.php")
        assert text == "chrome-html"
        _assert_browser_client_released(instances, browser_mode)
