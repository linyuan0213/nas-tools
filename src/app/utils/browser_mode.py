"""浏览器自动化模式工具函数.

提供从站点运行时配置构造 BrowserModeConfig 的能力, 以及渲染 HTML 归一化.
"""

from __future__ import annotations

import hashlib

from app.core.settings import settings
from app.infrastructure.http.config import BrowserModeConfig


def make_session_key(site_key: str, browser: BrowserModeConfig) -> str:
    """会话隔离键包含站点标识与浏览器配置指纹.

    配置变化(UA/代理/指纹画像/渲染模式)会自动换新 session.
    """
    config_hash = hashlib.md5(  # noqa: S303
        f"{browser.fingerprint_profile}:{browser.fp_profile_id}:{browser.user_agent}:{browser.proxy_url}:{browser.render_html}".encode()
    ).hexdigest()[:8]
    return f"{site_key}:{config_hash}"


def get_chrome_server_url() -> str | None:
    """返回 Chrome 服务器地址，仅在全局启用且已配置时返回。"""
    lab = settings.get("laboratory")
    if not lab.get("chrome_enabled", True):
        return None
    host = lab.get("chrome_server_host")
    return host.rstrip("/") if host else None


def get_chrome_api_key() -> str | None:
    """返回 nexus-chrome 访问凭证（复用 laboratory.chrome_admin_token）。

    nexus-chrome 设置 AUTH_PASSWORD 后启用认证：该配置可填管理端创建的
    API Key（ncmk_ 前缀，scope 建议 sessions+profiles），或 FP_ADMIN_TOKEN。
    未配置则不携带凭证（仅适用于 nexus-chrome 本地模式）。
    """
    lab = settings.get("laboratory") or {}
    token = str(lab.get("chrome_admin_token") or "").strip()
    return token or None


def build_browser_mode(
    site_info: dict,
    site_key: str,
    *,
    proxy_url: str | None = None,
    render_html: bool | None = None,
    server_url: str | None = None,
    fp_profile_id: str | None = None,
) -> BrowserModeConfig | None:
    """从站点运行时配置构造浏览器模式配置.

    开关来自 site_info["chrome"], 是用户在站点管理中维护的运行时配置,
    不是静态站点 JSON. fp_profile_id 为该用户的指纹画像（前端采集注入）;
    未显式传入时回退到系统配置的默认指纹（实验室 chrome_fp_profile_id），
    供全局后台流程（站点定时刷新 / RSS 自动化等无用户上下文场景）使用.
    """
    host = server_url
    if not host:
        host = get_chrome_server_url()
    if not host or not site_info.get("chrome"):
        return None

    if not fp_profile_id:
        fp_profile_id = str(settings.get("laboratory").get("chrome_fp_profile_id") or "") or None

    browser = BrowserModeConfig(
        enabled=True,
        server_url=host.rstrip("/"),
        session_key=site_key,
        site_key=site_key,
        fingerprint_profile="stealth",
        fp_profile_id=fp_profile_id,
        user_agent=site_info.get("ua"),
        proxy_url=proxy_url,
        render_html=render_html if render_html is not None else bool(site_info.get("browser_render")),
        api_key=get_chrome_api_key(),
        persistent_session=bool(site_info.get("browser_persistent")),
    )
    browser.session_key = make_session_key(site_key, browser)
    return browser
