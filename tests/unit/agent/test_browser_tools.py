"""浏览器工具（browser_fetch / browser_screenshot）单元测试 — mock BrowserSession"""

from typing import cast
from unittest.mock import patch

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.browser import (
    _clean_html,
    _validate_site_key,
    _validate_url,
    browser_fetch,
    browser_screenshot,
)
from app.infrastructure.chrome import BrowserSession
from app.infrastructure.chrome.challenge import wait_challenge_clear

# 浏览器 handler 不使用 ctx 内容，传一个类型化的占位
_CTX = cast(ToolContext, None)


class _FakeSession:
    """模拟 BrowserSession：navigate/html/screenshot"""

    def __init__(self, html="<html><body><h1>标题</h1><script>x</script><p>正文内容</p></body></html>", png="aGVsbG8="):
        self._html = html
        self._png = png

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self, delete_session=True):
        pass

    def navigate(self, url, timeout=30):
        self.url = url

    def html(self):
        return self._html

    def screenshot(self, tab_name=None, full_page=False):
        return {"png_base64": self._png, "size": 5}


class TestCleanHtml:
    def test_strips_scripts_and_nav(self):
        text = _clean_html("<html><nav>菜单</nav><h1>标题</h1><script>var x=1</script><p>正文</p></html>")
        assert "菜单" not in text
        assert "var x" not in text
        assert "标题" in text
        assert "正文" in text

    def test_invalid_html_fallback(self):
        text = _clean_html("<p>abc</p>")
        assert "abc" in text


class TestBrowserFetch:
    def test_returns_cleaned_text(self):
        with patch("app.agent.tools.handlers.browser._open_session", return_value=_FakeSession()):
            result = browser_fetch(_CTX, "https://example.com")
        assert result.success
        assert isinstance(result.data, dict)
        assert result.data["url"] == "https://example.com"
        assert "标题" in result.data["text"]

    def test_chrome_not_configured(self):
        with patch("app.agent.tools.handlers.browser._open_session", side_effect=RuntimeError("Chrome 服务器未配置")):
            result = browser_fetch(_CTX, "https://example.com")
        assert not result.success
        assert "Chrome" in result.error


class TestBrowserScreenshot:
    def test_saves_and_returns_url(self, tmp_path):
        fake = _FakeSession(png="aGVsbG8=")
        with (
            patch("app.agent.tools.handlers.browser._open_session", return_value=fake),
            patch("app.agent.tools.handlers.browser._static_data_dir", return_value=tmp_path),
            patch("app.agent.tools.handlers.browser.SiteRepository.get_config_site") as mock_sites,
        ):
            mock_sites.return_value = [type("S", (), {"NAME": "pttime"})()]
            result = browser_screenshot(_CTX, "https://example.com", site_key="pttime")
        assert result.success
        assert isinstance(result.data, dict)
        assert result.data["image"].startswith("/img/agent/screenshot_")
        assert (tmp_path / result.data["image"].rsplit("/", 1)[-1]).exists()

    def test_empty_png(self):
        fake = _FakeSession(png="")
        with patch("app.agent.tools.handlers.browser._open_session", return_value=fake):
            result = browser_screenshot(_CTX, "https://example.com")
        assert not result.success


class _ChallengeSession:
    """模拟先返回挑战页、后返回真实页的会话"""

    def __init__(self, attempts=2):
        self._attempts = attempts
        self._calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self, delete_session=True):
        pass

    def navigate(self, url, timeout=30):
        pass

    def html(self):
        self._calls += 1
        if self._calls <= self._attempts:
            return "<html>Checking your browser... DDoS protection</html>"
        return "<html>真实页面内容</html>"


class TestUrlValidation:
    def test_public_url_allowed(self):
        assert _validate_url("https://example.com") == "https://example.com"

    def test_private_ranges_rejected(self):
        for host in ("http://192.168.1.10/", "http://10.0.0.1/", "http://172.16.0.5/", "http://127.0.0.1/"):
            try:
                _validate_url(host)
            except ValueError:
                continue
            raise AssertionError(f"应拒绝内网 URL: {host}")

    def test_metadata_and_linklocal_rejected(self):
        for host in ("http://169.254.169.254/latest/meta-data/", "http://169.254.169.253/", "http://[::1]/"):
            try:
                _validate_url(host)
            except ValueError:
                continue
            raise AssertionError(f"应拒绝内部/元数据 URL: {host}")

    def test_bad_scheme_rejected(self):
        try:
            _validate_url("file:///etc/passwd")
        except ValueError:
            return
        raise AssertionError("应拒绝非 http(s) URL")


class TestSiteKeyValidation:
    def test_unknown_site_key_rejected(self):
        from unittest.mock import patch

        with patch("app.agent.tools.handlers.browser.SiteRepository.get_config_site", return_value=[]):
            try:
                _validate_site_key("not_exist_site")
            except ValueError:
                return
        raise AssertionError("未配置的 site_key 应被拒绝")

    def test_fail_closed_on_repo_error(self):
        from unittest.mock import patch

        with patch(
            "app.agent.tools.handlers.browser.SiteRepository.get_config_site", side_effect=RuntimeError("db down")
        ):
            try:
                _validate_site_key("pttime")
            except ValueError:
                return
        raise AssertionError("站点列表读取失败时应拒绝（fail-closed）而非放行")


class TestWaitChallenge:
    def test_waits_until_challenge_clears(self):

        session = _ChallengeSession(attempts=2)
        html = wait_challenge_clear(cast(BrowserSession, session), session.html())
        assert "Checking your browser" not in html
        assert "真实页面内容" in html
        assert session._calls >= 3

    def test_immediately_passes_without_challenge(self):

        html = wait_challenge_clear(cast(BrowserSession, None), "<html>正常页面</html>")
        assert "正常页面" in html
