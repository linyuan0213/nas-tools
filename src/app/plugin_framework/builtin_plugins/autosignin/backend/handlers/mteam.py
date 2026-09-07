import base64
import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.infrastructure.cache_system.cookiecloud_adapter import CookiecloudAdapter
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.utils.config_tools import get_ua
from app.utils.json_utils import JsonUtils

from .base import SigninResult, SiteSigninContext, SiteSigninHandler


class MTeam(SiteSigninHandler):
    """M-Team 签到处理器。

    通过调用 api.m-team.io 的 updateLastBrowse 接口完成签到/登录保号。
    请求需要：
    - localStorage.auth 中的 JWT Token
    - localStorage.did / visitorId / webversion
    - 从主站 JS 动态提取的 HMAC-SHA1 密钥
    """

    site_id = "mteam"
    _API_PATH = "/api/member/updateLastBrowse"
    _FALLBACK_SECRET = "HLkPcWmycL57mfJt"

    def __init__(self, plugin_ctx, rate_limiter=None):
        super().__init__(plugin_ctx, rate_limiter)

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        site_def = self._plugin_ctx.site_engine.get_by_id(ctx.site_id)
        home_url = self._resolve_home_url(site_def)
        local_storage_domain = self._resolve_local_storage_domain(home_url)

        self._plugin_ctx.emit("site.local_storage_sync", {})
        time.sleep(10)

        local_storage = CookiecloudAdapter().get_local_storage(local_storage_domain)
        if not local_storage:
            return SigninResult.fail(site, "LocalStorage 获取失败")

        jwt = local_storage.get("auth")
        did = local_storage.get("did")
        visitor_id = local_storage.get("visitorId")
        # localStorage 无 webversion 时使用当前站点前端版本
        webversion = local_storage.get("webversion") or "1170"
        if not jwt:
            return SigninResult.fail(site, "localStorage auth 为空")

        home_url = self._resolve_home_url(site_def)
        secret = self._fetch_secret(home_url, site) or self._FALLBACK_SECRET

        timestamp_ms = int(time.time() * 1000)
        timestamp_s = timestamp_ms // 1000
        signature = self._build_sign("POST", self._API_PATH, timestamp_ms, secret)

        # 认证相关请求头：必填核心项（站点维护 headers 无法覆盖）
        headers: dict[str, str] = {
            "accept": "application/json, text/plain, */*",
            "authorization": jwt,
            "cache-control": "no-cache",
            "did": did or "",
            "dnt": "1",
            "origin": home_url,
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": f"{home_url}/login",
            "ts": str(timestamp_s),
            "user-agent": ctx.ua or get_ua(),
            "visitorid": visitor_id or "",
            "webversion": webversion,
        }
        # 浏览器指纹类请求头（sec-ch-ua / accept-language / sec-fetch-* 等）取站点维护中维护的 headers
        maintained_headers = ctx.headers
        if isinstance(maintained_headers, str):
            try:
                maintained_headers = JsonUtils.loads(maintained_headers)
            except Exception:
                maintained_headers = {}
        if not isinstance(maintained_headers, dict):
            maintained_headers = {}
        core_keys = (
            "authorization",
            "did",
            "ts",
            "visitorid",
            "webversion",
            "origin",
            "referer",
            "user-agent",
            "content-type",
        )
        for hk, hv in maintained_headers.items():
            if hk and hv and hk.lower() not in core_keys:
                headers.setdefault(hk, hv)
        headers = {k: v for k, v in headers.items() if v}

        form = {
            "_timestamp": (None, str(timestamp_ms)),
            "_sgin": (None, signature),
        }

        api_base = self._resolve_api_base(site_def)
        url = f"{api_base}{self._API_PATH}"

        try:
            with HttpClient(
                config=HttpClientConfig(proxy_url=ctx.proxy_url),
                rate_limiter=self._rate_limiter,
            ) as client:
                res = client.post(url=url, files=form, headers=headers)
        except Exception as e:
            self._plugin_ctx.warn(f"{site} 签到请求失败: {e}")
            return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)

        return self._check_response(res, site)

    def _resolve_local_storage_domain(self, home_url: str) -> str:

        parsed = urlparse(home_url)
        host = parsed.hostname or "m-team.cc"
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host

    def _resolve_home_url(self, site_def: Any) -> str:
        domain = site_def.domain if site_def else "kp.m-team.cc"
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        return domain.rstrip("/")

    def _resolve_api_base(self, site_def: Any) -> str:
        if site_def and site_def.api and site_def.api.base_url:
            return site_def.api.base_url.rstrip("/")
        return "https://api.m-team.cc"

    def _fetch_secret(self, home_url: str, site: str) -> str | None:
        try:
            headers = {
                "User-Agent": get_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            with HttpClient(config=HttpClientConfig(default_headers=headers)) as client:
                home_res = client.get(url=f"{home_url}/index")
                main_match = re.search(r'src=["\']([^"\']*main\.(\w+)\.js)["\']', home_res.text)
                if not main_match:
                    return None
                js_url = main_match.group(1)
                if js_url.startswith("/"):
                    js_url = f"{home_url}{js_url}"
                js_res = client.get(url=js_url)
                m = re.search(r'\.join\(\[("[A-Za-z0-9]+"(?:,"[A-Za-z0-9]+")*)\],""\)', js_res.text)
                if not m:
                    return None
                chars = re.findall(r'"([A-Za-z0-9]+)"', m.group(1))
                secret = "".join(chars)
                if len(secret) >= 8:
                    self._plugin_ctx.debug(f"{site} 动态提取 M-Team 签名密钥成功")
                    return secret
        except Exception as e:
            self._plugin_ctx.warn(f"{site} 动态提取签名密钥失败: {e}")
        return None

    @staticmethod
    def _build_sign(method: str, path: str, timestamp_ms: int, secret: str) -> str:
        msg = f"{method}&{path}&{timestamp_ms}"
        sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha1).digest()
        return base64.b64encode(sig).decode()

    def _check_response(self, res: Any, site: str) -> SigninResult:
        text = res.text
        try:
            data = JsonUtils.loads(text)
        except Exception:
            return SigninResult.fail(site, "解析 JSON 响应失败")

        if data.get("code") in (0, "0") or data.get("success") is True:
            return SigninResult.success(site)

        message = str(data.get("message", "")).lower()
        if "重复" in message or "already" in message or "frequently" in message:
            return SigninResult.already(site)

        return SigninResult.fail(site, f"接口返回 {text[:200]}")
