"""HTTP Transport 实现浏览器自动化透明集成.

将 httpx2.Request 转发给 nexus-chrome 服务器的 /sessions/{id}/request 端点,
并把响应重新组装成 httpx2.Response, 使上层 HttpClient 调用无感知.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx2

import log
from app.infrastructure.http.config import BrowserModeConfig
from app.utils.render_normalize import normalize_rendered_html


def _make_session_key(site_key: str, browser: BrowserModeConfig) -> str:
    """会话隔离键：只包含影响浏览器指纹/环境的配置。

    ``render_html`` 是请求模式，不影响 Cookie 与会话状态，因此不计入 session_key。
    这样 ``render_html=False`` 过盾后产生的 Cookie 可以被 ``render_html=True`` 复用。
    """
    config_hash = hashlib.md5(
        f"{browser.fingerprint_profile}:{browser.fp_profile_id}:{browser.user_agent}:{browser.proxy_url}".encode()
    ).hexdigest()[:8]
    return f"{site_key}:{config_hash}"


class _ChromeServerClient:
    """对 Chrome 服务器的独立简化 HTTP 客户端, 避免复用 HttpClient 造成递归."""

    def __init__(self, server_url: str, timeout: float = 60.0, api_key: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key
        self._client = httpx2.Client(timeout=timeout, follow_redirects=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = f"{self.server_url}{path}"
        if self._api_key:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["Authorization"] = f"Bearer {self._api_key}"
            kwargs["headers"] = headers
        response = self._client.request(method, url, **kwargs)
        if raise_for_status:
            try:
                response.raise_for_status()
            except httpx2.HTTPError as e:
                log.error(f"[ChromeServer] {method} {path} failed: {e}")
                raise
        return response.json()

    def ensure_session(self, session_key: str, browser: BrowserModeConfig) -> dict[str, Any]:
        """幂等创建 session; 409/已存在时返回现有会话."""
        payload = {
            "session_id": session_key,
            "fingerprint_profile": browser.fingerprint_profile,
            "fp_profile_id": browser.fp_profile_id,
            "user_agent": browser.user_agent,
            "proxy": browser.proxy_url,
        }
        try:
            return self._request("POST", "/sessions", json=payload)
        except httpx2.HTTPStatusError as e:
            if e.response.status_code == 409:
                # 已存在，直接返回空数据，无需额外请求
                return {}
            raise

    def delete_session(self, session_key: str) -> None:
        """删除会话，关闭对应浏览器标签页；不存在时忽略."""
        try:
            self._request("DELETE", f"/sessions/{session_key}", raise_for_status=False)
        except Exception as e:  # noqa: BLE001
            log.warn(f"[ChromeServer] 删除会话 {session_key} 失败: {e}")

    def request(
        self,
        session_key: str,
        browser: BrowserModeConfig,
        url: str,
        method: str,
        headers: dict[str, str] | None,
        data: Any,
        cookie: str | None,
    ) -> dict[str, Any]:
        """调用聚合 /request 端点."""
        payload = {
            "url": url,
            "method": method,
            "headers": headers,
            "data": data,
            "navigate_if_challenge": browser.auto_navigate_on_challenge,
            "browser_fetch_on_challenge": browser.browser_fetch_on_challenge,
            "return_html": browser.render_html,
            "timeout": browser.navigate_timeout,
        }
        if cookie:
            payload["cookie"] = cookie
        return self._request("POST", f"/sessions/{session_key}/request", json=payload)

    def close(self) -> None:
        self._client.close()


class _BaseChromeTransport:
    """Transport 公共逻辑."""

    def __init__(self, browser: BrowserModeConfig, limits: httpx2.Limits | None = None):
        self._browser = browser
        self._session_key = browser.session_key or _make_session_key(browser.site_key, browser)
        self._server = _ChromeServerClient(
            browser.server_url,
            timeout=max(60.0, browser.navigate_timeout + 10),
            api_key=browser.api_key,
        )
        self._limits = limits

    def _build_response(self, request: httpx2.Request, payload: dict[str, Any]) -> httpx2.Response:
        """把 Chrome 服务器返回的 JSON 组装成 httpx2.Response."""
        data = payload.get("data", payload)
        status_code = int(data.get("status_code", 0))
        headers = dict(data.get("headers", {}))
        content: bytes
        if self._browser.render_html:
            text = normalize_rendered_html(data.get("html") or "")
            content = text.encode("utf-8")
            headers.setdefault("content-type", "text/html; charset=utf-8")
        else:
            body = data.get("body") or ""
            if isinstance(body, bytes):
                content = body
            else:
                encoding = "utf-8"
                ct = headers.get("content-type", "")
                if "charset=" in ct:
                    encoding = ct.split("charset=")[-1].split(";")[0].strip()
                content = body.encode(encoding)

        headers.setdefault("content-length", str(len(content)))
        return httpx2.Response(
            status_code=status_code,
            headers=headers,
            content=content,
            request=request,
        )

    def _ensure_session(self) -> None:
        self._server.ensure_session(self._session_key, self._browser)

    def _extract_cookie_header(self, request: httpx2.Request) -> str | None:
        cookie = request.headers.get("cookie")
        if cookie:
            return cookie
        # httpx 把 cookies 参数放在 Cookie 头里, 如果不在 headers 中, 也可能在 request extensions
        return None

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self._ensure_session()
        method = request.method
        url = str(request.url)
        headers = dict(request.headers)
        # 移除不应透传给 Chrome 服务器的头
        for key in list(headers.keys()):
            if key.lower() in ("host", "content-length"):
                headers.pop(key)
        cookie = self._extract_cookie_header(request)
        if cookie:
            headers.pop("cookie", None)

        data: Any = None
        if request.method in ("POST", "PUT", "PATCH"):
            data = request.content.decode("utf-8") if request.content else None

        payload = self._server.request(
            self._session_key,
            self._browser,
            url=url,
            method=method,
            headers=headers or None,
            data=data,
            cookie=cookie,
        )
        return self._build_response(request, payload)

    def close(self) -> None:
        # 持久会话：保留浏览器会话（含挑战/2FA 认证态），供后续请求复用；
        # 非持久会话在关闭时删除，释放浏览器标签页
        if not self._browser.persistent_session:
            try:
                self._server.delete_session(self._session_key)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[ChromeTransport] 关闭会话 {self._session_key} 失败: {e}")
        self._server.close()


class ChromeTransport(_BaseChromeTransport, httpx2.BaseTransport):
    """同步 Chrome Transport.

    _BaseChromeTransport 需排在 httpx2.BaseTransport 之前：
    BaseTransport.close() 是空实现，顺序颠倒会让会话删除永远不执行。
    """

    def __init__(self, browser: BrowserModeConfig, limits: httpx2.Limits | None = None):
        httpx2.BaseTransport.__init__(self)
        _BaseChromeTransport.__init__(self, browser, limits)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        return self._handle(request)


class AsyncChromeTransport(_BaseChromeTransport, httpx2.AsyncBaseTransport):
    """异步 Chrome Transport."""

    def __init__(self, browser: BrowserModeConfig, limits: httpx2.Limits | None = None):
        httpx2.AsyncBaseTransport.__init__(self)
        _BaseChromeTransport.__init__(self, browser, limits)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return self._handle(request)
