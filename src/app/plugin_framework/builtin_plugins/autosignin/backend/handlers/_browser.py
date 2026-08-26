"""浏览器自动化通用签到处理器。"""

import re
import threading
import time

from lxml import etree

from app.core.settings import settings
from app.infrastructure.chrome import BrowserSession
from app.infrastructure.chrome.challenge import (
    CHALLENGE_INDICATORS,
    has_pending_turnstile,
    wait_challenge_clear,
)
from app.sites.siteconf import SiteConf
from app.sites.utils import is_logged_in
from app.utils import ExceptionUtils
from app.utils.browser_mode import get_chrome_server_url

from .base import SigninResult, SiteSigninContext, SiteSigninHandler

# 串行化浏览器签到：并发启动多个浏览器会话会让 nexus-chrome 资源竞争，
# 导致 WAF/雷池挑战长时间无法通过（如我堡超时 120s），也减少同时打开的标签页
_BROWSER_SIGNIN_LOCK = threading.Lock()


class BrowserSigninHandler(SiteSigninHandler):
    """浏览器自动化通用处理器。"""

    site_id = "__browser__"

    def __init__(self, plugin_ctx, rate_limiter, config: dict):
        super().__init__(plugin_ctx, rate_limiter)
        self._config = config

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        site_def = self._plugin_ctx.site_engine.get_by_id(ctx.site_id)
        home_url = self._resolve_home_url(site_def, ctx)

        server_url = get_chrome_server_url()
        if not server_url:
            return SigninResult.fail(site, "Chrome 服务器未配置")

        self._plugin_ctx.info(f"开始浏览器签到：{site}")
        try:
            with _BROWSER_SIGNIN_LOCK:
                return self._do_signin(ctx, site, site_def, home_url, server_url)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return SigninResult.fail(site, str(e))

    def _do_signin(self, ctx, site, site_def, home_url, server_url) -> SigninResult:
        try:
            # 使用用户真实浏览器指纹画像（实验室默认画像），提高 Turnstile 等人机验证通过率
            lab = settings.get("laboratory") or {}
            fp_profile_id = str(lab.get("chrome_fp_profile_id") or "") or None
            with BrowserSession(site_key=site, server_url=server_url, fp_profile_id=fp_profile_id) as session:
                # 优先直接访问签到页：GET attendance 即完成签到，无需首页查找+点击，
                # 且等待签到页自身的 WAF/雷池挑战清除后再判定，避免误报失败
                attendance_url = self._resolve_attendance_url(home_url)
                result = session.navigate(attendance_url, cookie=ctx.cookie)
                html_text = result.get("html", "") or ""
                if not html_text:
                    return SigninResult.fail(site, "无法打开网站")
                html_text = self._wait_cloudflare(session, post_navigate=html_text)
                if CHALLENGE_INDICATORS.search(html_text):
                    return SigninResult.fail(site, f"挑战未通过: {html_text[:100]}")
                html_text = self._wait_embedded_turnstile(session, html_text)
                if has_pending_turnstile(html_text) and not (
                    self._already_signed(html_text) or self._success(html_text)
                ):
                    return SigninResult.fail(site, "人机验证未完成（Cloudflare Turnstile 未通过），请稍后重试")

                if self._already_signed(html_text):
                    return SigninResult.already(site)
                if self._success(html_text):
                    return SigninResult.custom(True, f"[{site}]浏览器签到成功")
                if not is_logged_in(html_text):
                    return SigninResult.fail(site, "登录状态异常")

                # 直接访问未生效（可能需要表单/按钮提交），回退首页查找签到按钮
                self._plugin_ctx.info(f"{site} 直接访问签到页未生效，回退首页查找签到按钮")
                result = session.navigate(home_url, cookie=ctx.cookie)
                html_text = result.get("html", "") or ""
                if not html_text:
                    return SigninResult.fail(site, "无法打开网站")
                html_text = self._wait_cloudflare(session, post_navigate=html_text)
                if not is_logged_in(html_text):
                    return SigninResult.fail(site, "登录状态异常")

                site_conf = SiteConf(self._plugin_ctx.site_engine)
                default_selectors = site_conf.get_checkin_conf()
                selectors = self._config.get("checkin_selectors") or default_selectors
                xpath = self._find_checkin_xpath(html_text, selectors)
                if not xpath:
                    return SigninResult.custom(True, f"[{site}]模拟登录成功")

                self._plugin_ctx.debug(f"{site} 点击签到按钮: {xpath}")
                session.click(f"xpath:{xpath}")
                html_text = self._wait_page_stable(session)
                # 点击后可能跳转至签到页并触发 WAF/雷池挑战，需等待挑战清除再判定
                html_text = self._wait_cloudflare(session, post_navigate=html_text)
                html_text = self._wait_embedded_turnstile(session, html_text)

                if self._success(html_text):
                    return SigninResult.custom(True, f"[{site}]浏览器签到成功")
                if self._already_signed(html_text):
                    return SigninResult.already(site)
                if self._two_factor(html_text):
                    return SigninResult.fail(site, "需要两步验证")
                if self._error(html_text):
                    return SigninResult.fail(site, "页面显示错误")
                return SigninResult.fail(site, "浏览器签到失败，未知原因")
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return SigninResult.fail(site, str(e))

    @staticmethod
    def _resolve_attendance_url(home_url: str) -> str:
        """构造签到页 URL（NexusPHP 系站点为 /attendance.php）."""
        base = home_url.rstrip("/")
        return f"{base}/attendance.php"

    @staticmethod
    def _wait_cloudflare(session: BrowserSession, post_navigate: str) -> str:
        return wait_challenge_clear(session, post_navigate, timeout=180)

    def _wait_embedded_turnstile(self, session: BrowserSession, html_text: str) -> str:
        """等待内嵌 Turnstile 完成（如观众签到页：验证通过后页面脚本自动提交表单）."""
        if not has_pending_turnstile(html_text):
            return html_text
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self._already_signed(html_text) or self._success(html_text):
                return html_text
            time.sleep(3)
            html_text = session.html()
            if not has_pending_turnstile(html_text):
                return html_text
        return html_text

    @staticmethod
    def _wait_page_stable(session: BrowserSession) -> str:
        prev = ""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            html_text = session.html()
            if html_text and html_text == prev:
                return html_text
            prev = html_text
            time.sleep(3)
        return session.html()

    def _resolve_home_url(self, site_def, ctx: SiteSigninContext) -> str:
        if site_def and site_def.domain:
            domain = site_def.domain
            if not domain.startswith(("http://", "https://")):
                domain = f"https://{domain}"
            return domain.rstrip("/")
        return ctx.site_url.rstrip("/")

    def _find_checkin_xpath(self, html_text: str, selectors: list[str]) -> str | None:
        html = etree.HTML(html_text)
        if html is None:
            return None
        for xpath in selectors:
            if html.xpath(xpath):
                return xpath
        return None

    @staticmethod
    def _already_signed(text: str) -> bool:
        return bool(re.search(r"已签|签到已得|今日已签|已签到|签到成功", text, re.IGNORECASE))

    def _success(self, text: str) -> bool:
        markers = self._config.get("success_markers", [])
        if markers:
            return any(re.search(m, text, re.IGNORECASE) for m in markers)
        return bool(re.search(r"已签|签到成功|获得.*积分|签到.*积分", text, re.IGNORECASE))

    @staticmethod
    def _two_factor(text: str) -> bool:
        return bool(re.search(r"完成两步验证|两步验证|2FA|二次验证", text, re.IGNORECASE))

    @staticmethod
    def _error(text: str) -> bool:
        return bool(re.search(r"错误|失败|异常|error|fail", text, re.IGNORECASE))
