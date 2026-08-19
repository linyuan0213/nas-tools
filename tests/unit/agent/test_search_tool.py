"""网页搜索工具（web_search）单元测试 — mock BrowserSession"""

from typing import cast
from unittest.mock import patch

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.search import (
    _parse_results,
    _real_url,
    _search_url,
    web_search,
)

_CTX = cast(ToolContext, None)

_GOOGLE_HTML = """
<html><body>
<div id="search">
  <div class="MjjYud">
    <a href="/url?q=https%3A%2F%2Fwww.python.org%2F&amp;sa=U"><h3>Python 官网</h3></a>
    <div class="VwiC3b">Python 编程语言官方网站。</div>
  </div>
  <div class="MjjYud">
    <a href="https://docs.python.org/3/"><h3>Python 文档</h3></a>
    <div class="IsZvec">官方文档与教程。</div>
  </div>
</div>
</body></html>
"""

_BING_HTML = """
<html><body>
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://www.bing.com/1">Bing 结果一</a></h2>
    <p>第一个结果的摘要。</p>
  </li>
  <li class="b_algo">
    <h2><a href="https://www.bing.com/2">Bing 结果二</a></h2>
    <p>第二个结果的摘要。</p>
  </li>
</ol>
</body></html>
"""

_BAIDU_HTML = """
<html><body>
<div class="result c-container">
  <h3 class="t"><a href="http://www.baidu.com/link?url=abc">百度结果一</a></h3>
  <span class="content-right_8Zs40">百度第一条摘要。</span>
</div>
<div class="result c-container">
  <h3 class="t"><a href="https://example.com/direct">百度结果二</a></h3>
  <span class="c-abstract">百度第二条摘要。</span>
</div>
</body></html>
"""


class _FakeSession:
    def __init__(self, html=""):
        self._html = html

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


class TestSearchUrl:
    def test_urls_per_engine(self):
        assert "google.com/search" in _search_url("google", "x", 5)
        assert "bing.com/search" in _search_url("bing", "x", 5)
        assert "baidu.com/s" in _search_url("baidu", "x", 5)

    def test_query_urlencoded(self):
        url = _search_url("google", "a b&c", 5)
        assert "q=a+b%26c" in url

    def test_limit_params(self):
        assert "num=7" in _search_url("google", "x", 7)
        assert "count=7" in _search_url("bing", "x", 7)
        assert "rn=7" in _search_url("baidu", "x", 7)


class TestRealUrl:
    def test_google_redirect_decoded(self):
        assert _real_url("/url?q=https%3A%2F%2Fwww.python.org%2F&sa=U") == "https://www.python.org/"

    def test_baidu_redirect_kept_when_no_target(self):
        assert _real_url("http://www.baidu.com/link?url=abc") == "http://www.baidu.com/link?url=abc"

    def test_direct_url_unchanged(self):
        assert _real_url("https://docs.python.org/3/") == "https://docs.python.org/3/"


class TestParseResults:
    def test_google(self):
        results = _parse_results("google", _GOOGLE_HTML)
        assert len(results) == 2
        assert results[0]["title"] == "Python 官网"
        assert results[0]["url"] == "https://www.python.org/"
        assert "官方网站" in results[0]["snippet"]

    def test_bing(self):
        results = _parse_results("bing", _BING_HTML)
        assert len(results) == 2
        assert results[0]["title"] == "Bing 结果一"
        assert results[0]["url"] == "https://www.bing.com/1"
        assert "摘要" in results[0]["snippet"]

    def test_baidu(self):
        results = _parse_results("baidu", _BAIDU_HTML)
        assert len(results) == 2
        assert results[0]["title"] == "百度结果一"
        assert results[1]["url"] == "https://example.com/direct"
        assert "摘要" in results[1]["snippet"]

    def test_invalid_html_returns_empty(self):
        assert _parse_results("google", "not html") == []


class TestWebSearchHandler:
    def test_returns_results(self):
        with patch(
            "app.agent.tools.handlers.search._open_session",
            return_value=_FakeSession(html=_GOOGLE_HTML),
        ):
            result = web_search(_CTX, "python", engine="google", limit=5)
        assert result.success
        assert isinstance(result.data, dict)
        assert result.data["engine"] == "google"
        assert result.data["query"] == "python"
        assert len(result.data["results"]) == 2

    def test_empty_query_rejected(self):
        result = web_search(_CTX, "  ")
        assert not result.success
        assert "不能为空" in result.error

    def test_unknown_engine_rejected(self):
        result = web_search(_CTX, "x", engine="yahoo")
        assert not result.success

    def test_limit_clamped(self):
        with patch(
            "app.agent.tools.handlers.search._open_session",
            return_value=_FakeSession(html=_GOOGLE_HTML),
        ):
            result = web_search(_CTX, "python", limit=100)
        assert isinstance(result.data, dict)
        assert len(result.data["results"]) <= 10

    def test_chrome_failure_returns_error(self):
        with patch("app.agent.tools.handlers.search._open_session", side_effect=RuntimeError("chrome down")):
            result = web_search(_CTX, "python")
        assert not result.success
        assert "搜索失败" in result.error

    def test_no_results_reported(self):
        with patch(
            "app.agent.tools.handlers.search._open_session",
            return_value=_FakeSession(html="<html><body>captcha</body></html>"),
        ):
            result = web_search(_CTX, "python")
        assert not result.success
        assert "未解析到搜索结果" in result.error
