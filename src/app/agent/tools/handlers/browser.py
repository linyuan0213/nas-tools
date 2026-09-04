"""浏览器工具 handler — 基于基础设施 Chrome 能力（nexus-chrome 服务）

复用站点会话隔离键：传 site_key 时可携带该站点已登录 Cookie 访问登录后页面。
"""

import base64
import ipaddress
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lxml import html as lhtml

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.core.settings import settings
from app.db.repositories.site_repository import SiteRepository
from app.infrastructure.chrome import BrowserSession
from app.infrastructure.chrome.challenge import wait_challenge_clear
from app.utils.browser_mode import get_chrome_server_url

_MAX_TEXT_CHARS = 6000
_SCREENSHOT_MAX_B64 = 5 * 1024 * 1024


def _clean_html(html_str: str) -> str:
    """HTML → 可读文本（去脚本/样式/导航/页脚，压缩空行）"""
    if not html_str:
        return ""
    try:
        doc: Any = lhtml.fromstring(html_str)
        for tag in doc.xpath("//script | //style | //noscript | //nav | //footer | //iframe"):
            parent = tag.getparent()
            if parent is not None:
                parent.remove(tag)
        text = doc.text_content() or ""
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html_str)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _validate_url(url: str) -> str:
    """校验浏览器目标 URL：仅 http(s)，拒绝回环/私网/链路本地/云元数据/保留地址等内部目标（防 SSRF）"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"不支持的 URL：{url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"URL 无法解析：{url}") from e
    for info in infos:
        ip_text = str(info[4][0]).split("%")[0]
        ip = ipaddress.ip_address(ip_text)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or ip == ipaddress.ip_address("169.254.169.254")
            or ip == ipaddress.ip_address("169.254.169.253")
        ):
            raise ValueError(f"URL 指向内部网络，已拒绝：{url}")
    return url


def _validate_site_key(site_key: str | None) -> str | None:
    """校验站点标识：仅允许已配置站点（避免任意 site_key 复用他人已登录 Cookie）"""
    if not site_key:
        return None
    try:
        keys = {s.NAME for s in SiteRepository().get_config_site() if getattr(s, "NAME", None)}
    except Exception as e:  # noqa: BLE001
        # fail-closed：站点列表读取失败时拒绝，而不是放行任意 site_key
        raise ValueError(f"站点列表校验失败，拒绝 site_key：{e}") from e
    if site_key not in keys:
        raise ValueError(f"未配置的站点标识：{site_key}")
    return site_key


def _default_fp_profile_id() -> str | None:
    """实验室配置的真实用户指纹画像（用户浏览器登录同步），未同步时为 None（走 stealth）"""
    lab = settings.get("laboratory") or {}
    return str(lab.get("chrome_fp_profile_id") or "") or None


def _open_session(site_key: str | None) -> BrowserSession:
    server_url = get_chrome_server_url()
    if not server_url:
        raise RuntimeError("Chrome 服务器未配置（系统设置 → 实验室 → Chrome 服务器地址）")
    session = BrowserSession(
        site_key=site_key or "agent",
        server_url=server_url,
        fp_profile_id=_default_fp_profile_id(),
    )
    session.__enter__()
    return session


def _close_session(session: BrowserSession) -> None:
    """关闭会话但不删除：保留已通过人机验证/登录的 Cookie，供后续访问复用"""
    session.close(delete_session=False)


def browser_fetch(ctx: ToolContext, url: str, site_key: str | None = None, timeout: int = 30) -> ToolResult:
    """浏览器访问网页并返回清理后的文本（截断）"""
    try:
        _validate_url(url)
        site_key = _validate_site_key(site_key)
        session = _open_session(site_key)
        try:
            session.navigate(url, timeout=int(timeout or 30))
            html_str = session.html()
            html_str = wait_challenge_clear(session, html_str)
        finally:
            _close_session(session)
    except Exception as e:
        return ToolResult(success=False, error=f"浏览器访问失败: {e}")
    text = _clean_html(html_str)[:_MAX_TEXT_CHARS]
    return ToolResult(
        success=True,
        data={"url": url, "site_key": site_key, "text": text, "truncated": len(text) >= _MAX_TEXT_CHARS},
    )


def browser_screenshot(ctx: ToolContext, url: str, site_key: str | None = None, full_page: bool = False) -> ToolResult:
    """浏览器截图并保存到静态目录，返回可访问的图片 URL"""
    try:
        _validate_url(url)
        site_key = _validate_site_key(site_key)
        session = _open_session(site_key)
        try:
            session.navigate(url, timeout=30)
            html_str = session.html()
            # 等待人机验证通过后再截图，避免截到 Cloudflare 验证页
            wait_challenge_clear(session, html_str)
            result = session.screenshot(full_page=bool(full_page))
        finally:
            _close_session(session)
    except Exception as e:
        return ToolResult(success=False, error=f"截图失败: {e}")
    png_b64 = result.get("png_base64") or ""
    if not png_b64:
        return ToolResult(success=False, error="截图结果为空")
    try:
        raw = base64.b64decode(png_b64)
    except Exception as e:
        return ToolResult(success=False, error=f"截图解码失败: {e}")
    if len(raw) > _SCREENSHOT_MAX_B64:
        return ToolResult(success=False, error="截图过大，无法保存")

    # 保存到静态目录 /static/agent/screenshot_<ts>_<site>.png
    static_dir = _static_data_dir()
    try:
        site_token = re.sub(r"[^\w-]", "_", site_key or "web")
        name = f"screenshot_{int(time.time())}_{site_token}.png"
        path = static_dir / name
        path.write_bytes(raw)
    except Exception as e:
        return ToolResult(success=False, error=f"截图保存失败: {e}")
    return ToolResult(
        success=True,
        data={
            "url": url,
            "site_key": site_key,
            "image": f"/img/agent/{name}",
            "size": len(raw),
            "note": "图片 URL 已给出，可在回答中以 markdown 图片展示",
        },
    )


def _static_data_dir():
    """静态目录（data_path/static/agent），与应用 /static 挂载对应"""
    agent_dir = Path(settings.data_path) / "static" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir
