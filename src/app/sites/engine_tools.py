"""引擎内部工具 — 从 engine.py 拆分"""

import os
import re
from typing import Any

import httpx2
from lxml import etree

import log
from app.infrastructure.http.auth import ApiKeyAuth, BearerAuth, CookieAuth
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.utils.config_tools import get_proxies
from app.utils.json_utils import JsonUtils


def _build_auth(engine: Any, site: Any, user_config: dict) -> tuple[dict, httpx2.Auth | None]:
    """构建全局认证（每个请求通用），返回 (headers, auth)。

    认证信息同时写入 headers（向后兼容）并返回 auth 对象（供 httpx 使用）。
    """
    headers = user_config.get("headers", {}) or {}
    if isinstance(headers, str):
        try:
            headers = JsonUtils.loads(headers)
        except Exception:
            headers = {}
    auth = None
    auth_type = site.api.auth.get("type", "") if site.api else ""

    if auth_type == "api_key":
        hdr = site.api.auth.get("header_name", "x-api-key")
        key = user_config.get("api_key", "")
        # 向后兼容：旧配置可能把 api_key 放在 cookie 字段
        if not key:
            key = user_config.get("cookie", "")
        if key:
            headers[hdr] = key
            auth = ApiKeyAuth(key=hdr, value=key)
    elif auth_type == "bearer":
        token = user_config.get("bearer_token", "")
        # 向后兼容：旧配置可能把 bearer token 放在 cookie/api_key 字段
        if not token:
            token = user_config.get("api_key", "") or user_config.get("cookie", "")
        if token and not token.startswith("Bearer "):
            token = f"Bearer {token}"
        if token:
            headers["Authorization"] = token
            raw_token = token.removeprefix("Bearer ")
            auth = BearerAuth(raw_token)
    elif auth_type == "cookie":
        cookie = user_config.get("cookie", "")
        if cookie:
            auth = CookieAuth(cookie)
    elif auth_type == "csrf":
        hdr = site.api.auth.get("header_name", "X-CSRF-TOKEN")
        token = engine._resolve_auth_token(site, user_config, "csrf")
        if token:
            headers[hdr] = token
        cookie = user_config.get("cookie", "")
        if cookie:
            auth = CookieAuth(cookie)

    headers["Content-Type"] = headers.get("Content-Type", "application/json;charset=utf-8")
    ua_override = site.api.auth.get("user_agent") if site.api and site.api.auth else None
    if ua_override is not None:
        headers["User-Agent"] = ua_override
    elif user_config.get("ua"):
        headers["User-Agent"] = user_config.get("ua")
    return headers, auth


def _get_rate_limit_kwargs(engine: Any, site: Any) -> dict:
    """获取限流参数（供 HttpClient 使用）."""
    site_limiter = getattr(engine, "site_limiter", None)
    if not site_limiter or not site or not getattr(site, "id", None):
        return {}
    rate_config = site_limiter.get_rate(str(site.id))
    if not rate_config:
        return {}
    return {"rate_limit_key": f"site:{site.id}", "rate_limit_rate": rate_config[0]}


def _build_headers(engine: Any, site: Any, user_config: dict) -> dict:
    """返回包含认证信息的 headers 字典。"""
    headers, auth = _build_auth(engine, site, user_config)
    if auth is not None and hasattr(auth, "_cookies"):
        cookie_dict = getattr(auth, "_cookies", {})
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        if cookie_str:
            headers["Cookie"] = cookie_str
    return headers


def _call_endpoint(
    engine: Any,
    cfg: dict,
    site: Any,
    user_config: dict,
    template_vars: dict,
    credential: str = "",
    download_dir: str = "",
    download: bool = False,
) -> bool | list[dict] | None:
    method = cfg.get("method", "GET")
    path = cfg.get("path", "").format(**template_vars)
    base = site.api.base_url.rstrip("/") if site.api else ""
    url = f"{base}{'/' if not path.startswith('/') else ''}{path}"

    headers, auth = engine._build_auth(site, user_config)
    proxy = get_proxies() if user_config.get("proxy") else None
    proxy_url = proxy.get("http") if proxy else None

    rate_limiter = getattr(engine, "site_limiter", None)
    rate_limiter_engine = rate_limiter.engine if rate_limiter else None
    rl_kwargs = _get_rate_limit_kwargs(engine, site)

    if download:
        headers.pop("Content-Type", None)
        try:
            res = HttpClient(
                config=HttpClientConfig(proxy_url=proxy_url),
                rate_limiter=rate_limiter_engine,
            ).get(url=url, headers=headers, auth=auth, **rl_kwargs)
            if download_dir:
                fname = os.path.join(download_dir, f"{credential}.zip") if credential else "subtitle.zip"
                with open(fname, "wb") as f:
                    f.write(res.content)
                return True
            return False
        except Exception:
            return False

    client = HttpClient(
        config=HttpClientConfig(proxy_url=proxy_url),
        rate_limiter=rate_limiter_engine,
    )
    try:
        if method == "POST":
            b = cfg.get("body") or {}
            body = {}
            for k, v in b.items():
                if isinstance(v, str):
                    body[k] = v.format(**template_vars)
                elif isinstance(v, dict):
                    body[k] = {sk: sv.format(**template_vars) if isinstance(sv, str) else sv for sk, sv in v.items()}
                else:
                    body[k] = v
            # 始终发送 JSON 请求体（空 body 也发送 "{}"），部分站点对空 body 会返回“请求参数错误”
            post_data = JsonUtils.dumps(body, separators=(",", ":"))
            res = client.post(url=url, data=post_data, headers=headers, auth=auth, **rl_kwargs)
        else:
            params = cfg.get("params")
            if params:
                params = {k: v.format(**template_vars) if isinstance(v, str) else v for k, v in params.items()}
            headers.pop("Content-Type", None)
            res = client.get(url=url, params=params, headers=headers, auth=auth, **rl_kwargs)
        return res.json()
    except Exception as e:
        log.error(f"[SiteEngine]请求异常 {url}: {e}")
        return None


def _resolve_auth_token(engine: Any, site: Any, user_config: dict, token_type: str) -> str | None:
    cache_key = f"{site.id}:{token_type}"
    if cache_key in engine._auth_cache:
        return engine._auth_cache[cache_key]
    if token_type == "csrf":
        token = _fetch_csrf_token(engine, site, user_config)
        log.debug(f"[SiteEngine]{site.name} CSRF token: {'OK' if token else 'FAIL'}")
    elif token_type == "passkey":
        token = _fetch_passkey(engine, site, user_config)
    else:
        token = None
    if token:
        engine._auth_cache[cache_key] = token
    return token


def _fetch_csrf_token(engine: Any, site: Any, user_config: dict) -> str | None:
    auth = site.api.auth
    csrf_url = auth.get("csrf_url", "").replace("{domain}", site.api.base_url.rstrip("/"))
    if not csrf_url:
        csrf_url = site.api.base_url.rstrip("/")
    cookie = user_config.get("cookie", "")
    ua = user_config.get("ua", "")
    proxy = get_proxies() if user_config.get("proxy") else None
    proxy_url = proxy.get("http") if proxy else None
    rate_limiter = getattr(engine, "site_limiter", None)
    rate_limiter_engine = rate_limiter.engine if rate_limiter else None
    rl_kwargs = _get_rate_limit_kwargs(engine, site)
    try:
        res = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url),
            rate_limiter=rate_limiter_engine,
        ).get(url=csrf_url, headers={"User-Agent": ua}, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs)
    except Exception as e:
        log.warn(f"[SiteEngine]{site.name} 获取CSRF失败: {e!r}")
        return None
    selector = auth.get("csrf_selector", "")
    selector_type = auth.get("csrf_selector_type", "regex")
    if selector_type == "regex":
        match = re.search(selector, res.text)
        return match.group(1) if match else None
    html_doc: Any = etree.HTML(res.text)
    els: Any = html_doc.xpath(selector)
    if els and hasattr(els[0], "text") and els[0].text:
        return els[0].text
    if els and hasattr(els[0], "attrs") and "content" in els[0].attrs:
        return els[0].attrs["content"]
    return None


def _fetch_passkey(engine: Any, site: Any, user_config: dict) -> str | None:
    auth = site.api.auth
    url = auth.get("passkey_url", "")
    if not url:
        return None
    method = auth.get("passkey_method", "GET")
    response_key = auth.get("passkey_response_key", "data.passkey")
    base = site.api.base_url.rstrip("/")
    url = f"{base}{'/' if not url.startswith('/') else ''}{url}"
    headers = engine._build_headers(site, user_config)
    headers.pop("Content-Type", None)
    cookie = user_config.get("cookie", "")
    proxy = get_proxies() if user_config.get("proxy") else None
    proxy_url = proxy.get("http") if proxy else None
    rate_limiter = getattr(engine, "site_limiter", None)
    rate_limiter_engine = rate_limiter.engine if rate_limiter else None
    rl_kwargs = _get_rate_limit_kwargs(engine, site)
    try:
        client = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url),
            rate_limiter=rate_limiter_engine,
        )
        if method.upper() == "GET":
            res = client.get(url=url, headers=headers, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs)
        else:
            res = client.post(url=url, headers=headers, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs)
        data = res.json()
        keys = response_key.split(".")
        val = data
        for k in keys:
            val = val.get(k) if isinstance(val, dict) else None
            if val is None:
                break
        return val
    except Exception:
        return None


def _call_html_endpoint(engine: Any, url: str, html_cfg: dict, user_config: dict, site: Any = None) -> dict | None:
    method = html_cfg.get("method", "GET").upper()
    path = html_cfg.get("path", "")
    params = html_cfg.get("params") or {}
    body = html_cfg.get("body") or {}
    selectors = html_cfg.get("selectors") or {}

    domain = url.rstrip("/") if url else ""
    path_with_slash = f"/{path.lstrip('/')}" if path else ""
    req_url = f"{domain}{path_with_slash}"

    cookie = user_config.get("cookie", "")
    ua = user_config.get("ua", "")
    headers = {"User-Agent": ua} if ua else {}
    proxy = get_proxies() if user_config.get("proxy") else None
    proxy_url = proxy.get("http") if proxy else None

    rate_limiter = getattr(engine, "site_limiter", None)
    rate_limiter_engine = rate_limiter.engine if rate_limiter else None
    rl_kwargs = _get_rate_limit_kwargs(engine, site)

    try:
        client = HttpClient(
            config=HttpClientConfig(proxy_url=proxy_url),
            rate_limiter=rate_limiter_engine,
        )
        if method == "POST":
            res = client.post(
                url=req_url, data=body, headers=headers, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs
            )
        else:
            res = client.get(
                url=req_url, params=params, headers=headers, auth=CookieAuth(cookie) if cookie else None, **rl_kwargs
            )
    except Exception:
        return None

    html_doc: Any = etree.HTML(res.text)
    result = {}
    for field_name, cfg in selectors.items():
        xpath = cfg.get("xpath", "")
        if not xpath:
            result[field_name] = cfg.get("default", "")
            continue
        try:
            els: Any = html_doc.xpath(xpath)
        except Exception:
            els = []
        if not els:
            result[field_name] = cfg.get("default", "")
            continue
        attr = cfg.get("attribute", "")
        if attr and hasattr(els[0], "attrib") and attr in els[0].attrib:
            result[field_name] = els[0].attrib[attr]
        elif hasattr(els[0], "text"):
            result[field_name] = "".join(e for e in els[0].xpath(".//text()") if e).strip()
        elif isinstance(els[0], str):
            result[field_name] = els[0]
        else:
            result[field_name] = str(els[0])
    return result
