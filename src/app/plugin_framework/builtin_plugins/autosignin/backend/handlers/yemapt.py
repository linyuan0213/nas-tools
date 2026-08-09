"""YemaPT 签到处理器 — SPA 页面 + ALTCHA 工作量证明验证。

YemaPT 的签到是 SPA（hash 路由）页面，由 ALTCHA（工作量证明）保护：
必须先点击 ALTCHA 复选框触发 PoW 计算，验证通过后再点"立即签到"。
纯 HTTP 直签 API 会因缺少 altchaPayload 被拒绝，故用浏览器自动化完成。
"""

from __future__ import annotations

import re
import time

from app.infrastructure.chrome import BrowserSession
from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.base import (
    SigninResult,
    SiteSigninContext,
    SiteSigninHandler,
)
from app.utils.browser_mode import get_chrome_server_url

_CHECKIN_PATH = "/#/user/growth?tab=checkIn"
_CHECKIN_DEFAULT_BASE = "https://www.yemapt.org"

# 已签到（含签到后提示"已签到，明日继续"）
_SIGNED_RE = re.compile(r"已签到", re.IGNORECASE)
# 登录状态（页面出现个人中心导航/用户名即视为已登录）
_LOGGED_IN_RE = re.compile(r"个人中心|退出|签到中心", re.IGNORECASE)

_ALTCHA_CHECKBOX = "css:.altcha-checkbox input[type=checkbox]"
_CHECKIN_BUTTON = "text=立即签到"
_ALTCHA_PAYLOAD_JS = (
    "return (function(){var i=document.querySelector('input[name=altchaPayload]');"
    "return i && i.value ? '1' : '';})()"
)
_ALTCHA_TIMEOUT = 60
_PAGE_SETTLE = 4
_POLL_INTERVAL = 3


class YemaPT(SiteSigninHandler):
    """YemaPT 站点专用签到（浏览器 + ALTCHA）。"""

    site_id = "yemapt"

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        server_url = get_chrome_server_url()
        if not server_url:
            return SigninResult.fail(site, "Chrome 服务器未配置")

        checkin_url = self._resolve_checkin_url(ctx)
        self._plugin_ctx.info(f"[{site}] 开始浏览器签到（ALTCHA）: {checkin_url}")
        try:
            with BrowserSession(site_key=site, server_url=server_url) as session:
                # 1. 打开签到页（SPA hash 路由），等待渲染
                session.navigate(checkin_url, cookie=ctx.cookie)
                time.sleep(_PAGE_SETTLE)
                html_text = session.html() or ""

                if self._already_signed(html_text):
                    return SigninResult.already(site)
                if not _LOGGED_IN_RE.search(html_text):
                    return SigninResult.fail(site, "登录状态异常")

                # 2. 点击 ALTCHA 复选框触发工作量证明
                self._plugin_ctx.debug(f"[{site}] 点击 ALTCHA 验证框")
                session.click(_ALTCHA_CHECKBOX)

                # 3. 等待 PoW 计算完成（altchaPayload 填充）
                if not self._wait_altcha_verified(session):
                    return SigninResult.fail(site, "ALTCHA 验证未完成（超时）")

                # 4. 点击"立即签到"
                self._plugin_ctx.debug(f"[{site}] 点击立即签到")
                session.click(_CHECKIN_BUTTON)
                time.sleep(_PAGE_SETTLE)

                # 5. 判定结果
                html_text = session.html() or ""
                if self._already_signed(html_text):
                    return SigninResult.success(site)
                return SigninResult.fail(site, "点击签到后未生效")
        except Exception as e:  # noqa: BLE001
            self._plugin_ctx.warn(f"[{site}] 浏览器签到异常: {e}")
            return SigninResult.fail(site, str(e))

    def _resolve_checkin_url(self, ctx: SiteSigninContext) -> str:
        """签到页 URL：域名取自站点配置，仅 SPA hash 路由为站点特有。"""
        base = (ctx.site_url or _CHECKIN_DEFAULT_BASE).rstrip("/")
        return f"{base}{_CHECKIN_PATH}"

    def _wait_altcha_verified(self, session: BrowserSession, timeout: int = _ALTCHA_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if session.execute(_ALTCHA_PAYLOAD_JS):
                    return True
            except Exception as e:  # noqa: BLE001
                self._plugin_ctx.debug(f"[ALTCHA] 等待验证执行异常，继续轮询: {e}")
            time.sleep(_POLL_INTERVAL)
        return False

    @staticmethod
    def _already_signed(text: str) -> bool:
        return bool(_SIGNED_RE.search(text or ""))
