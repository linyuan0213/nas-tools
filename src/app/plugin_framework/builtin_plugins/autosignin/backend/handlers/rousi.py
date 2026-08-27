"""Rousi（rousi.pro，Peergo 架构）自动签到。

新架构流程：
1. GET /api/v1/session（带 cookie）→ 获取 csrf_token
2. POST /api/v1/me/attendance，带 x-csrf-token + 随机 idempotency-key，body {"mode":"fixed"}
"""

import uuid

from app.infrastructure.http.auth import CookieAuth
from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.base import (
    SigninResult,
    SiteSigninContext,
    SiteSigninHandler,
)
from app.utils import StringUtils
from app.utils.json_utils import JsonUtils


class RousiSigninHandler(SiteSigninHandler):
    site_id = "rousi"

    _ALREADY_MARKERS = ("已签到", "已经签到", "今日已签到", "already", "today")

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        cookie = ctx.cookie
        if not cookie:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)

        base_url = StringUtils.get_base_url(ctx.site_url)
        client = self._http_client(ctx)
        auth = CookieAuth(cookie) if cookie else None
        ua = ctx.ua
        headers = {"User-Agent": ua} if ua else {}

        # 1. 获取 CSRF Token
        try:
            session_res = client.get(url=f"{base_url}/api/v1/session", headers=headers, auth=auth)
        except Exception:
            return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)

        if session_res.status_code == 401:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)

        try:
            session_data = JsonUtils.loads(session_res.text)
        except Exception:
            return SigninResult.fail(site, "获取 session 响应解析失败")

        csrf_token = session_data.get("csrf_token") if isinstance(session_data, dict) else None
        if not csrf_token:
            return SigninResult.fail(site, "未获取到 CSRF Token")

        # 2. 签到
        api_headers = {
            "x-csrf-token": csrf_token,
            "idempotency-key": str(uuid.uuid4()),
            "Content-Type": "application/json",
            "Origin": base_url,
            "Referer": f"{base_url}/account/api-key",
        }
        if ua:
            api_headers["User-Agent"] = ua

        try:
            att_res = client.post(
                url=f"{base_url}/api/v1/me/attendance",
                json={"mode": "fixed"},
                headers=api_headers,
                auth=auth,
            )
        except Exception:
            return SigninResult.fail(site, SigninResult.REQUEST_FAILED)

        if att_res.status_code == 401:
            return SigninResult.fail(site, SigninResult.COOKIE_EXPIRED)

        try:
            data = JsonUtils.loads(att_res.text)
        except Exception:
            return SigninResult.fail(site, f"签到响应解析失败 HTTP {att_res.status_code}")

        if not isinstance(data, dict):
            return SigninResult.fail(site, f"签到接口返回 {att_res.text[:200]}")

        # 3. 结果判断
        if data.get("attendance_date"):
            reward = data.get("total_reward")
            if reward is not None:
                return SigninResult.custom(True, f"[{site}]签到成功，获得奖励 {reward}")
            return SigninResult.success(site)

        if data.get("code") == "attendance_already_claimed":
            return SigninResult.already(site)

        message = " ".join(str(data.get(k) or "") for k in ("message", "title", "detail"))
        if any(marker in message for marker in self._ALREADY_MARKERS):
            return SigninResult.already(site)

        return SigninResult.fail(site, f"签到接口返回 {att_res.text[:200]}")
