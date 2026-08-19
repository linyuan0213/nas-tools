"""网页搜索工具 handler — 通过内置 Chrome 服务（nexus-chrome）抓取搜索引擎结果页并解析"""

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from lxml import html as lhtml

import log
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.browser import _close_session, _open_session, _validate_url
from app.infrastructure.chrome.challenge import wait_challenge_clear

_SEARCH_URLS = {
    "google": "https://www.google.com/search",
    "bing": "https://www.bing.com/search",
    "baidu": "https://www.baidu.com/s",
}

_MAX_RESULTS = 10


def _nodes(node: Any, expr: str) -> list[Any]:
    """xpath 结果归一化为 list（lxml 可能返回单值/标量）"""
    result = node.xpath(expr)
    return result if isinstance(result, list) else ([result] if result else [])


def _search_url(engine: str, query: str, limit: int) -> str:
    """构造搜索引擎结果页 URL"""
    params = {"q": query}
    if engine == "bing":
        params["count"] = str(limit)
    elif engine == "baidu":
        params["rn"] = str(limit)
    else:
        params["num"] = str(limit)
    return f"{_SEARCH_URLS[engine]}?{urlencode(params)}"


def _real_url(url: str) -> str:
    """Google/Baidu 跳转链接还原为真实地址（/url?q=... 或 /link?url=...）"""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if "google.com" in host or "baidu.com" in host or parsed.path.startswith("/url"):
            qs = parse_qs(parsed.query)
            target = (qs.get("q") or qs.get("url") or [""])[0]
            if target.startswith("http"):
                return target
    except Exception as e:  # noqa: BLE001
        log.debug(f"[WebSearch]跳转链接解析失败，保留原文: {e}")
    return url


def _parse_results(engine: str, html_str: str) -> list[dict]:
    """按引擎解析搜索结果：title / url / snippet"""
    results: list[dict] = []
    seen: set[str] = set()
    try:
        doc = lhtml.fromstring(html_str)
    except Exception:  # noqa: BLE001
        return results

    if engine == "google":
        for a in _nodes(doc, "//a[@href][.//h3]"):
            url = _real_url(a.get("href") or "")
            title = " ".join(str(x) for x in _nodes(a, ".//h3//text()")).strip()
            if not title or url in seen:
                continue
            containers = _nodes(
                a,
                "./ancestor::div[contains(@class,'tF2Cxc')] | ./ancestor::div[contains(@class,'MjjYud')]",
            )
            snippet = ""
            if containers:
                snippet = " ".join(
                    " ".join(
                        str(x)
                        for x in _nodes(
                            containers[0],
                            ".//div[contains(@class,'VwiC3b') or contains(@class,'IsZvec')]//text()",
                        )
                    ).split()
                )
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": snippet})
    elif engine == "bing":
        for li in _nodes(doc, "//li[contains(@class,'b_algo')]"):
            a = _nodes(li, ".//h2/a") or _nodes(li, ".//a[@href]")
            if not a:
                continue
            url = a[0].get("href") or ""
            title = " ".join(str(x) for x in _nodes(a[0], ".//text()")).strip()
            if not title or url in seen:
                continue
            snippet = " ".join(" ".join(str(x) for x in _nodes(li, ".//p//text()")).split())
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": snippet})
    elif engine == "baidu":
        for block in _nodes(doc, "//div[contains(@class,'result') and contains(@class,'c-container')]"):
            a = _nodes(block, ".//h3//a")
            if not a:
                continue
            url = _real_url(a[0].get("href") or "")
            title = " ".join(str(x) for x in _nodes(a[0], ".//text()")).strip()
            if not title or url in seen:
                continue
            snippet = " ".join(
                " ".join(
                    str(x)
                    for x in _nodes(
                        block,
                        ".//span[contains(@class,'content-right') or contains(@class,'c-abstract')]//text()",
                    )
                ).split()
            )
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


def web_search(ctx: ToolContext, query: str, engine: str = "google", limit: int = 5) -> ToolResult:
    """通过内置 Chrome 服务在搜索引擎检索网页，返回结构化结果列表"""
    query = str(query or "").strip()
    if not query:
        return ToolResult(success=False, error="搜索关键词不能为空")
    if engine not in _SEARCH_URLS:
        return ToolResult(success=False, error=f"不支持的搜索引擎：{engine}")
    limit = max(1, min(int(limit or 5), _MAX_RESULTS))
    url = _search_url(engine, query, limit)
    try:
        _validate_url(url)
        session = _open_session(None)
        try:
            session.navigate(url, timeout=30)
            html_str = session.html()
            html_str = wait_challenge_clear(session, html_str)
        finally:
            _close_session(session)
    except Exception as e:  # noqa: BLE001
        log.warn(f"[WebSearch]搜索失败: {e}")
        return ToolResult(success=False, error=f"搜索失败: {e}")
    results = _parse_results(engine, html_str)[:limit]
    if not results:
        return ToolResult(success=False, error="未解析到搜索结果（可能遇到人机验证或页面结构变化）")
    return ToolResult(success=True, data={"query": query, "engine": engine, "results": results})


HANDLERS = {
    "web_search": web_search,
}
