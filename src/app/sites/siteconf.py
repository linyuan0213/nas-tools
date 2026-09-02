"""站点配置 — 委托 engine 的 JSON 定义，不再依赖 sites.dat"""


class SiteConf:
    _SITE_CHECKIN_XPATH = [
        '//a[@id="signed"]',
        '//a[contains(@href, "attendance")]',
        '//a[contains(text(), "签到")]',
        '//a/b[contains(text(), "签 到")]',
        '//span[@id="sign_in"]/a',
        '//a[contains(@href, "addbonus")]',
        '//input[@class="dt_button"][contains(@value, "打卡")]',
        '//a[contains(@href, "sign_in")]',
        '//a[contains(@onclick, "do_signin")]',
        '//a[@id="do-attendance"]',
        '//shark-icon-button[@href="attendance.php"]',
    ]
    _SITE_SUBTITLE_XPATH = [
        '//td[@class="rowhead"][text()="字幕"]/following-sibling::td//a/@href',
    ]
    _SITE_LOGIN_XPATH = {
        "username": ['//input[@name="username"]', '//input[@id="form_item_username"]', '//input[@id="username"]'],
        "password": ['//input[@name="password"]', '//input[@id="form_item_password"]', '//input[@id="password"]'],
        "captcha": ['//input[@name="imagestring"]', '//input[@name="captcha"]', '//input[@id="form_item_captcha"]'],
        "captcha_img": [
            '//img[@alt="CAPTCHA"]/@src',
            '//img[@alt="SECURITY CODE"]/@src',
            '//img[@id="LAY-user-get-vercode"]/@src',
            '//img[contains(@src,"/api/getCaptcha")]/@src',
        ],
        "submit": [
            '//input[@type="submit"]',
            '//button[@type="submit"]',
            '//button[@lay-filter="login"]',
            '//button[@lay-filter="formLogin"]',
            '//input[@type="button"][@value="登录"]',
        ],
        "error": ["//table[@class='main']//td[@class='text']/text()"],
        "twostep": ['//input[@name="two_step_code"]', '//input[@name="2fa_secret"]'],
    }

    def __init__(self, site_engine):
        self._refresh()
        self._site_engine = site_engine

    def _get_site_engine(self):
        return self._site_engine

    def _refresh(self):
        pass

    def get_checkin_conf(self):
        return self._SITE_CHECKIN_XPATH

    def get_subtitle_conf(self):
        return self._SITE_SUBTITLE_XPATH

    def get_login_conf(self):
        return self._SITE_LOGIN_XPATH

    def get_grap_conf(self, url=None):
        site_def = self._get_site_engine().get_by_url(url) if url else None
        if site_def and site_def.html and site_def.html.conf:
            return site_def.html.conf
        if site_def and site_def.torrent_attr:
            resp = (site_def.torrent_attr or {}).get("response", {})
            conf = {}
            if resp.get("free_key"):
                conf["FREE"] = True
            if resp.get("2xfree_key"):
                conf["2XFREE"] = True
            if resp.get("hr_key"):
                conf["HR"] = True
            if conf:
                return conf
        return {}

    def check_torrent_attr(
        self,
        torrent_url,
        cookie,
        api_key=None,
        bearer_token=None,
        ua=None,
        headers=None,
        proxy=False,
        chrome=False,
    ):
        return self._get_site_engine().resolve_torrent_attr(
            torrent_url=torrent_url,
            cookie=cookie,
            api_key=api_key,
            bearer_token=bearer_token,
            ua=ua,
            headers=headers,
            proxy=proxy,
            chrome=chrome,
        )
