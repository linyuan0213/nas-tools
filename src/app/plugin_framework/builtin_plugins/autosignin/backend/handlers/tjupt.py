import os
import re
import time
from io import BytesIO
from typing import cast

from bs4 import BeautifulSoup
from lxml import etree
from PIL import Image

import log
from app.infrastructure.chrome import BrowserSession
from app.infrastructure.http.auth import CookieAuth
from app.infrastructure.http.client import HttpClient, HttpClientError
from app.infrastructure.http.config import HttpClientConfig
from app.plugin_framework.builtin_plugins.autosignin.backend.handlers.base import (
    SigninResult,
    SiteSigninContext,
    SiteSigninHandler,
)
from app.utils import StringUtils
from app.utils.browser_mode import get_chrome_server_url
from app.utils.chinese_utils import to_simplified
from app.utils.json_utils import JsonUtils
from app.utils.path_utils import get_temp_path


class Tjupt(SiteSigninHandler):
    site_id = "tjupt"
    _sign_regex = ['<a href="attendance.php">今日已签到</a>']
    _succeed_regex = [
        "这是您的首次签到，本次签到获得\\d+个魔力值。",
        "签到成功，这是您的第\\d+次签到，已连续签到\\d+天，本次签到获得\\d+个魔力值。",
        "重新签到成功，本次签到获得\\d+个魔力值",
    ]

    def __init__(self, plugin_ctx, rate_limiter=None):
        super().__init__(plugin_ctx, rate_limiter)

    @property
    def _answer_file(self) -> str:
        answer_path = os.path.join(get_temp_path(), "signin")
        return os.path.join(answer_path, "tjupt.json")

    def signin(self, ctx: SiteSigninContext) -> SigninResult:
        site = ctx.site
        signurl = ctx.site_url
        cookie = ctx.cookie
        ua = ctx.ua
        base_url = StringUtils.get_base_url(signurl)
        attendance_url = base_url + "/attendance.php"

        if not os.path.exists(os.path.dirname(self._answer_file)):
            os.makedirs(os.path.dirname(self._answer_file), exist_ok=True)

        try:
            html_res = HttpClient(config=HttpClientConfig()).get(
                url=attendance_url,
                headers={"User-Agent": ua} if ua else None,
                auth=CookieAuth(cookie) if cookie else None,
                raise_for_status=False,
            )
        except HttpClientError:
            return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)

        if html_res.status_code != 200:
            return SigninResult.fail(site, SigninResult.SITE_UNREACHABLE)
        if cookie_result := self._check_cookie(html_res.text, site):
            return cookie_result
        if self.sign_in_result(html_res=html_res.text, regexs=self._sign_regex):
            return SigninResult.already(site)

        html = etree.HTML(html_res.text)
        if not html:
            return SigninResult.fail(site, "签到失败")

        img_url = str(cast(list, html.xpath('//table[@class="captcha"]//img/@src'))[0] or "")
        captcha_img_hash = ""
        if img_url:
            if not img_url.startswith("http"):
                img_url = base_url + "/" + img_url.lstrip("/")
            try:
                captcha_res = HttpClient().get(url=img_url, raise_for_status=False)
                if captcha_res.status_code == 200:
                    captcha_img = Image.open(BytesIO(captcha_res.content))
                    captcha_img_hash = self._tohash(captcha_img)
                    self._plugin_ctx.debug(f"签到验证码图片hash {captcha_img_hash}")
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Sites]忽略异常: {e}")

        values = cast(list, html.xpath("//input[@name='answer']/@value"))
        options = cast(list, html.xpath("//input[@name='answer']/following-sibling::text()"))
        if not values or not options:
            return SigninResult.fail(site, "未获取到答案选项")

        answers = list(zip(list(values), list(options), strict=False))
        self._plugin_ctx.debug(f"获取到所有签到选项 {answers}")

        existing_answers = {}
        try:
            with open(self._answer_file) as f:
                existing_answers = JsonUtils.loads(f.read())
            captcha_answer = existing_answers.get(captcha_img_hash)
            if captcha_answer and captcha_img_hash:
                for value, answer in answers:
                    if str(captcha_answer) == str(answer):
                        return self._do_signin(answer=value, ctx=ctx, attendance_url=attendance_url)
        except (FileNotFoundError, OSError):
            self._plugin_ctx.debug("查询本地已知答案失败，继续请求豆瓣查询")

        for value, answer in answers:
            if answer:
                try:
                    db_res = HttpClient().get(
                        url=f"https://movie.douban.com/j/subject_suggest?q={answer}",
                        raise_for_status=False,
                    )
                except HttpClientError:
                    self._plugin_ctx.debug(f"签到选项 {answer} 未查询到豆瓣数据")
                    continue
                if db_res.status_code != 200:
                    self._plugin_ctx.debug(f"签到选项 {answer} 未查询到豆瓣数据")
                    continue

                db_answers = JsonUtils.loads(db_res.text)
                if not isinstance(db_answers, list):
                    db_answers = [db_answers]
                if len(db_answers) == 0:
                    self._plugin_ctx.debug(f"签到选项 {answer} 查询到豆瓣数据为空")
                    continue

                for db_answer in db_answers:
                    answer_img_url = db_answer["img"]
                    try:
                        answer_img_res = HttpClient().get(url=answer_img_url, raise_for_status=False)
                    except HttpClientError:
                        self._plugin_ctx.debug(f"签到答案 {answer} {answer_img_url} 请求失败")
                        continue
                    if answer_img_res.status_code != 200:
                        self._plugin_ctx.debug(f"签到答案 {answer} {answer_img_url} 请求失败")
                        continue

                    answer_img = Image.open(BytesIO(answer_img_res.content))
                    answer_img_hash = self._tohash(answer_img)
                    self._plugin_ctx.debug(f"签到答案图片hash {answer} {answer_img_hash}")

                    score = self._comparehash(captcha_img_hash, answer_img_hash)
                    self._plugin_ctx.info(f"签到图片与选项 {answer} 豆瓣图片相似度 {score}")
                    if score > 0.9:
                        return self._do_signin(
                            answer=value,
                            ctx=ctx,
                            attendance_url=attendance_url,
                            existing_answers=existing_answers,
                            captcha_img_hash=captcha_img_hash,
                        )
            time.sleep(5)

        self._plugin_ctx.error("豆瓣图片匹配，未获取到匹配答案")

        image_search_url = f"https://lens.google.com/uploadbyurl?url={img_url}"
        server_url = get_chrome_server_url()
        if not server_url:
            self._plugin_ctx.info("Chrome 服务器未配置或未启用，跳过 Google 识图")
            return SigninResult.fail(site, "未配置 Chrome 服务器")
        with BrowserSession(site_key="tjupt", server_url=server_url) as session:
            session.navigate(image_search_url)
            html_text = session.html()
        search_results = BeautifulSoup(html_text, "lxml").find_all("div", class_="UAiK1e")
        if not search_results:
            self._plugin_ctx.info("Google识图失败，未获取到识图结果")
        else:
            res_count = len(search_results)
            search_results_text = "@".join([to_simplified(result.text) for result in search_results if result.text])
            count_results = []
            count_flag = False
            for value, answer in answers:
                answer_re = re.compile(re.sub(r"\d$", "", str(answer)))
                count = len(re.findall(answer_re, search_results_text))
                if count >= min(res_count, 3):
                    count_flag = True
                count_results.append((count, value, answer))
            if count_flag:
                count_results.sort(key=lambda x: x[0], reverse=True)
                log_content = f"Google识图结果共{res_count}条，各选项出现次数："
                for result in count_results:
                    count, value, answer = result
                    log_content += f"{answer} {count}次；"
                log_content += f"其中选项 {count_results[0][2]} 出现次数最多，认为是正确答案"
                self._plugin_ctx.info(log_content)
                return self._do_signin(
                    answer=count_results[0][1],
                    ctx=ctx,
                    attendance_url=attendance_url,
                    existing_answers=existing_answers,
                    captcha_img_hash=captcha_img_hash,
                )
            else:
                self._plugin_ctx.info("Google识图结果中未有选项符合条件")

        return SigninResult.fail(site, "未获取到匹配答案")

    def _do_signin(
        self, answer, ctx: SiteSigninContext, attendance_url: str, existing_answers=None, captcha_img_hash=None
    ):
        site = ctx.site
        cookie = ctx.cookie
        ua = ctx.ua

        data = {"answer": answer, "submit": "提交"}

        try:
            sign_in_res = HttpClient(config=HttpClientConfig()).post(
                url=attendance_url,
                data=data,
                headers={"User-Agent": ua} if ua else None,
                auth=CookieAuth(cookie) if cookie else None,
                raise_for_status=False,
            )
        except HttpClientError:
            return SigninResult.fail(site, SigninResult.REQUEST_FAILED)

        if sign_in_res.status_code != 200:
            return SigninResult.fail(site, SigninResult.REQUEST_FAILED)

        sign_status = SiteSigninHandler.sign_in_result(html_res=sign_in_res.text, regexs=self._succeed_regex)
        if sign_status:
            if existing_answers is not None and captcha_img_hash:
                self._write_local_answer(
                    existing_answers=existing_answers or {}, captcha_img_hash=captcha_img_hash, answer=answer
                )
            return SigninResult.success(site)
        return SigninResult.fail(site, "请到页面查看")

    def _write_local_answer(self, existing_answers: dict, captcha_img_hash: str, answer):
        try:
            existing_answers[captcha_img_hash] = answer
            with open(self._answer_file, "w") as f:
                f.write(JsonUtils.dumps(existing_answers, indent=4))
        except (FileNotFoundError, OSError):
            pass

    @staticmethod
    def _tohash(img, shape=(10, 10)):
        img = img.resize(shape)
        gray = img.convert("L")
        s = 0
        hash_str = ""
        for i in range(shape[1]):
            for j in range(shape[0]):
                s = s + gray.getpixel((j, i))
        avg = s / (shape[0] * shape[1])
        for i in range(shape[1]):
            for j in range(shape[0]):
                if gray.getpixel((j, i)) > avg:
                    hash_str = hash_str + "1"
                else:
                    hash_str = hash_str + "0"
        return hash_str

    @staticmethod
    def _comparehash(hash1, hash2, shape=(10, 10)):
        n = 0
        if len(hash1) != len(hash2):
            return -1
        for i in range(len(hash1)):
            if hash1[i] == hash2[i]:
                n = n + 1
        return n / (shape[0] * shape[1])
