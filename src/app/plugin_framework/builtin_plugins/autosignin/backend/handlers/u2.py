"""U2 签到处理器。"""

import random
import re
from datetime import datetime

from app.infrastructure.http.auth import CookieAuth
from app.utils import StringUtils

from .base import SigninResult, SiteSigninContext, SiteSigninHandler


class U2(SiteSigninHandler):
    site_id = "u2"
    _ALREADY_REGEXS = [
        r'<a href="showup.php">已签到</a>',
        r'<a href="showup.php">Show Up</a>',
        r'<a href="showup.php">Показать</a>',
        r'<a href="showup.php">已簽到</a>',
    ]
    _SUCCESS_TEXT = "window.location.href = 'showup.php';\u003c/script\u003e"

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        if not ctx.cookie:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)

        if datetime.now().hour < 9:
            return SigninResult.fail(site, "9点前不签到")

        base_url = StringUtils.get_base_url(ctx.site_url)
        showup_url = base_url + "/showup.php"
        base_headers = {"User-Agent": ctx.ua} if ctx.ua else {}

        with self._http_client(ctx) as client:
            try:
                index_res = client.get(
                    url=showup_url,
                    headers=base_headers,
                    auth=CookieAuth(ctx.cookie),
                )
            except Exception as e:
                self._plugin_ctx.warn(f"{site} 首页请求失败: {e}")
                return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)

        text = index_res.text
        if "login.php" in text:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)

        if self.sign_in_result(text, self._ALREADY_REGEXS):
            return SigninResult.already(site)

        params = self._extract_form_params(text)
        if not params:
            return SigninResult.fail(site, "未获取到签到参数")

        req, hash_str, form, submit_name, submit_value = params
        answer_num = random.randint(0, min(3, len(submit_name) - 1))
        data = {
            "req": req,
            "hash": hash_str,
            "form": form,
            "message": "一切随缘~",
            submit_name[answer_num]: submit_value[answer_num],
        }

        with self._http_client(ctx) as client:
            try:
                sign_res = client.post(
                    url=showup_url + "?action=show",
                    data=data,
                    headers=base_headers,
                    auth=CookieAuth(ctx.cookie),
                )
            except Exception as e:
                self._plugin_ctx.warn(f"{site} 签到请求失败: {e}")
                return SigninResult.fail(site, SigninResult.REQUEST_FAILED)

        if self._SUCCESS_TEXT in sign_res.text:
            return SigninResult.success(site)

        return SigninResult.fail(site, "签到失败，未知原因")

    def _extract_form_params(self, text: str) -> tuple | None:
        req = self._extract_input(text, "req")
        hash_str = self._extract_input(text, "hash")
        form = self._extract_input(text, "form")
        submit_names = re.findall(r'<input[^\u003e]*type=["\']submit["\'][^\u003e]*name=["\']([^"\']+)["\']', text)
        submit_values = re.findall(r'<input[^\u003e]*type=["\']submit["\'][^\u003e]*value=["\']([^"\']+)["\']', text)
        if not req or not hash_str or not form or not submit_names or not submit_values:
            return None
        return req, hash_str, form, submit_names, submit_values

    @staticmethod
    def _extract_input(text: str, name: str) -> str | None:
        m = re.search(rf'<input[^\u003e]*name=["\']{name}["\'][^\u003e]*value=["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
        return None
