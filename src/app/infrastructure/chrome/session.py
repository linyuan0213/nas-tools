"""交互式浏览器会话客户端.

用于签到、登录、验证码等多步交互流程, 直接调用 nexus-chrome 的 Session API.
与 ChromeTransport 共用同一个会话隔离键, 过盾产生的 Cookie 可被后续 HTTP 抓取复用.
"""

from __future__ import annotations

from typing import Any

import httpx2

import log
from app.utils.browser_mode import get_chrome_api_key


class _BaseBrowserSession:
    """BrowserSession 公共实现."""

    def __init__(
        self,
        site_key: str,
        *,
        server_url: str,
        fingerprint: str = "stealth",
        user_agent: str | None = None,
        proxy_url: str | None = None,
        fp_profile_id: str | None = None,
        timeout: float = 60.0,
        api_key: str | None = None,
    ):
        self.site_key = site_key
        self.server_url = server_url.rstrip("/")
        self.fingerprint = fingerprint
        self.user_agent = user_agent
        self.proxy_url = proxy_url
        self.fp_profile_id = fp_profile_id
        self.timeout = timeout
        self.session_id = site_key
        # 未显式传入时读取全局配置（laboratory.chrome_admin_token）
        self._api_key = api_key if api_key is not None else get_chrome_api_key()

    def _auth_headers(self) -> dict[str, str]:
        """认证请求头：nexus-chrome 启用 AUTH_PASSWORD 时必须携带。"""
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _session_url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    def _ensure_session_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "fingerprint_profile": self.fingerprint,
            "fp_profile_id": self.fp_profile_id,
            "user_agent": self.user_agent,
            "proxy": self.proxy_url,
        }


class BrowserSession(_BaseBrowserSession):
    """同步交互式浏览器会话."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._client = httpx2.Client(timeout=self.timeout, follow_redirects=True, headers=self._auth_headers())

    def __enter__(self) -> BrowserSession:
        self._ensure_session()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _ensure_session(self) -> None:
        try:
            self._client.post(f"{self.server_url}/sessions", json=self._ensure_session_payload())
        except httpx2.HTTPStatusError as e:
            if e.response.status_code != 409:
                raise

    def navigate(
        self,
        url: str,
        *,
        cookie: str | None = None,
        referer: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        payload = {"url": url, "cookie": cookie, "referer": referer, "timeout": timeout}
        response = self._client.post(self._session_url(f"/sessions/{self.session_id}/navigate"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    def html(self) -> str:
        response = self._client.get(self._session_url(f"/sessions/{self.session_id}/html"))
        response.raise_for_status()
        data = response.json().get("data", {})
        return data.get("html", "")

    def cookies(self, domain: str | None = None) -> dict[str, Any]:
        params = {"domain": domain} if domain else {}
        response = self._client.get(self._session_url(f"/sessions/{self.session_id}/cookies"), params=params)
        response.raise_for_status()
        return response.json().get("data", {})

    def click(self, selector: str) -> None:
        response = self._client.post(
            self._session_url(f"/sessions/{self.session_id}/click"), json={"selector": selector}
        )
        response.raise_for_status()

    def input(self, selector: str, text: str) -> None:
        response = self._client.post(
            self._session_url(f"/sessions/{self.session_id}/input"),
            json={"selector": selector, "text": text},
        )
        response.raise_for_status()

    def execute(self, script: str) -> Any:
        response = self._client.post(self._session_url(f"/sessions/{self.session_id}/execute"), json={"script": script})
        response.raise_for_status()
        return response.json().get("data", {}).get("result")

    def fetch(self, url: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
        payload = {"url": url, "method": method, **kwargs}
        response = self._client.post(self._session_url(f"/sessions/{self.session_id}/fetch"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    def screenshot(self, tab_name: str | None = None, full_page: bool = False) -> dict[str, Any]:
        """对指定（或活动）标签页截图，返回 {png_base64, size, ...}"""
        payload = {"tab_name": tab_name, "full_page": full_page}
        response = self._client.post(self._session_url(f"/sessions/{self.session_id}/screenshot"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    def close(self, delete_session: bool = True) -> None:
        if delete_session:
            try:
                self._client.delete(self._session_url(f"/sessions/{self.session_id}"))
            except Exception as e:
                log.warn(f"[BrowserSession] 关闭会话 {self.session_id} 失败: {e}")
        self._client.close()


class AsyncBrowserSession(_BaseBrowserSession):
    """异步交互式浏览器会话."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._client = httpx2.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self._auth_headers())

    async def __aenter__(self) -> AsyncBrowserSession:
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def _ensure_session(self) -> None:
        try:
            await self._client.post(f"{self.server_url}/sessions", json=self._ensure_session_payload())
        except httpx2.HTTPStatusError as e:
            if e.response.status_code != 409:
                raise

    async def navigate(
        self,
        url: str,
        *,
        cookie: str | None = None,
        referer: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        payload = {"url": url, "cookie": cookie, "referer": referer, "timeout": timeout}
        response = await self._client.post(self._session_url(f"/sessions/{self.session_id}/navigate"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    async def html(self) -> str:
        response = await self._client.get(self._session_url(f"/sessions/{self.session_id}/html"))
        response.raise_for_status()
        data = response.json().get("data", {})
        return data.get("html", "")

    async def cookies(self, domain: str | None = None) -> dict[str, Any]:
        params = {"domain": domain} if domain else {}
        response = await self._client.get(self._session_url(f"/sessions/{self.session_id}/cookies"), params=params)
        response.raise_for_status()
        return response.json().get("data", {})

    async def click(self, selector: str) -> None:
        response = await self._client.post(
            self._session_url(f"/sessions/{self.session_id}/click"), json={"selector": selector}
        )
        response.raise_for_status()

    async def input(self, selector: str, text: str) -> None:
        response = await self._client.post(
            self._session_url(f"/sessions/{self.session_id}/input"),
            json={"selector": selector, "text": text},
        )
        response.raise_for_status()

    async def execute(self, script: str) -> Any:
        response = await self._client.post(
            self._session_url(f"/sessions/{self.session_id}/execute"), json={"script": script}
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("result")

    async def fetch(self, url: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
        payload = {"url": url, "method": method, **kwargs}
        response = await self._client.post(self._session_url(f"/sessions/{self.session_id}/fetch"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    async def screenshot(self, tab_name: str | None = None, full_page: bool = False) -> dict[str, Any]:
        """对指定（或活动）标签页截图，返回 {png_base64, size, ...}"""
        payload = {"tab_name": tab_name, "full_page": full_page}
        response = await self._client.post(self._session_url(f"/sessions/{self.session_id}/screenshot"), json=payload)
        response.raise_for_status()
        return response.json().get("data", {})

    async def close(self, delete_session: bool = True) -> None:
        if delete_session:
            try:
                await self._client.delete(self._session_url(f"/sessions/{self.session_id}"))
            except Exception as e:
                log.warn(f"[AsyncBrowserSession] 关闭会话 {self.session_id} 失败: {e}")
        await self._client.aclose()
