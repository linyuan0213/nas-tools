import time

import log
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.ocr import OcrRecognizer
from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.base import (
    SigninResult,
    SiteSigninContext,
    SiteSigninHandler,
)
from app.utils import StringUtils
from app.utils.json_utils import JsonUtils


class HDSky(SiteSigninHandler):
    site_id = "hdsky"

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        signurl = ctx.site_url
        cookie = ctx.cookie
        ua = ctx.ua
        base_url = StringUtils.get_base_url(signurl)
        client = self._http_client(ctx)

        try:
            index_res = client.get(
                url=base_url,
                headers={"User-Agent": ua} if ua else None,
                auth=CookieAuth(cookie) if cookie else None,
            )
        except Exception:
            return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)

        if cookie_result := self._check_cookie(index_res.text, site):
            return cookie_result
        if "已签到" in index_res.text:
            return SigninResult.already(site)

        img_hash = None
        captcha_url = base_url + "/image_code_ajax.php"
        image_headers = (
            {"User-Agent": ua, "Referer": base_url + "/index.php"} if ua else {"Referer": base_url + "/index.php"}
        )
        res_times = 0
        while not img_hash and res_times <= 3:
            try:
                image_res = client.post(
                    url=captcha_url,
                    data={"action": "new"},
                    headers=image_headers,
                    auth=CookieAuth(cookie) if cookie else None,
                )
                image_json = JsonUtils.loads(image_res.text)
                if image_json["success"]:
                    img_hash = image_json["code"]
                    break
                res_times += 1
                self._plugin_ctx.debug(f"获取{site}验证码失败，重试次数 {res_times}")
                time.sleep(1)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Sites]忽略异常: {e}")

        if not img_hash:
            return SigninResult.fail(site, "未获取到验证码")

        img_get_url = base_url + f"/image.php?action=regimage&imagehash={img_hash}"
        self._plugin_ctx.debug(f"获取到{site}验证码链接 {img_get_url}")

        times = 0
        ocr_result = None
        while times <= 3:
            try:
                ocr_result = (
                    OcrRecognizer()
                    .recognize(
                        {"task_type": "captcha", "image_url": img_get_url},
                        cookie=cookie,
                        ua=ua,
                    )
                    .text
                    or ""
                )
            except Exception:
                ocr_result = ""
            self._plugin_ctx.debug(f"ocr识别{site}验证码 {ocr_result}")
            if ocr_result and len(ocr_result) == 6:
                self._plugin_ctx.info(f"ocr识别{site}验证码成功 {ocr_result}")
                break
            times += 1
            self._plugin_ctx.debug(f"ocr识别{site}验证码失败，重试次数 {times}")
            time.sleep(1)

        if not ocr_result:
            return SigninResult.fail(site, "未获取到验证码")

        data = {"action": "showup", "imagehash": img_hash, "imagestring": ocr_result}
        signin_url = base_url + "/showup.php"
        try:
            res = client.post(
                url=signin_url,
                data=data,
                headers=image_headers,
                auth=CookieAuth(cookie) if cookie else None,
            )
            res_json = JsonUtils.loads(res.text)
            if res_json["success"]:
                return SigninResult.success(site)
            if str(res_json.get("message", "")) == "date_unmatch":
                return SigninResult.already(site)
            if str(res_json.get("message", "")) == "invalid_imagehash":
                return SigninResult.fail(site, "验证码错误")
            fail_msg = str(res_json.get("message", "")) or res.text[:200]
            self._plugin_ctx.warn(f"{site} 签到响应未知: {res.text[:200]}")
            return SigninResult.fail(site, f"签到结果 {fail_msg}")
        except Exception as e:  # noqa: BLE001
            self._plugin_ctx.warn(f"{site} 签到请求异常: {e}")
            return SigninResult.fail(site, f"签到请求失败: {e}")
