from datetime import timedelta, timezone
import os
import pickle
import random
import time
import re
import json
from functools import lru_cache

from loguru import logger
from lxml import etree
from urllib.parse import urlsplit

from app.helper.drissionpage_helper import DrissionPageHelper
from app.sites import Sites
from app.utils import ExceptionUtils, StringUtils, RequestUtils, JsonUtils
from app.utils.commons import SingletonMeta
from config import MT_URL, Config
import log


class SiteConf(metaclass=SingletonMeta):
    # 站点签到支持的识别XPATH
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
        '//shark-icon-button[@href="attendance.php"]'
    ]

    # 站点详情页字幕下载链接识别XPATH
    _SITE_SUBTITLE_XPATH = [
        '//td[@class="rowhead"][text()="字幕"]/following-sibling::td//a/@href',
    ]

    # 站点登录界面元素XPATH
    _SITE_LOGIN_XPATH = {
        "username": [
            '//input[@name="username"]',
            '//input[@id="form_item_username"]',
            '//input[@id="username"]'
        ],
        "password": [
            '//input[@name="password"]',
            '//input[@id="form_item_password"]',
            '//input[@id="password"]'
        ],
        "captcha": [
            '//input[@name="imagestring"]',
            '//input[@name="captcha"]',
            '//input[@id="form_item_captcha"]'
        ],
        "captcha_img": [
            '//img[@alt="CAPTCHA"]/@src',
            '//img[@alt="SECURITY CODE"]/@src',
            '//img[@id="LAY-user-get-vercode"]/@src',
            '//img[contains(@src,"/api/getCaptcha")]/@src'
        ],
        "submit": [
            '//input[@type="submit"]',
            '//button[@type="submit"]',
            '//button[@lay-filter="login"]',
            '//button[@lay-filter="formLogin"]',
            '//input[@type="button"][@value="登录"]'
        ],
        "error": [
            "//table[@class='main']//td[@class='text']/text()"
        ],
        "twostep": [
            '//input[@name="two_step_code"]',
            '//input[@name="2fa_secret"]'
        ]
    }

    # 促销/HR的匹配XPATH
    _RSS_SITE_GRAP_CONF = {}

    # 种子详情
    URL_DETAIL_TEMPLATES = {
        'm-team': '/detail/{tid}',
        'fsm': "/api/Torrents/details?tid={tid}&page=1",
        'yemapt': "/api/torrent/fetchTorrentDetail?id={tid}&firstView=false",
        'star-space': "/p_torrent/video_detail.php?tid={tid}",
        'default': '/details.php?id={tid}'
    }
    def __init__(self):
        self.init_config()

    def init_config(self):
        try:
            with open(os.path.join(Config().get_inner_config_path(),
                                   "sites.dat"),
                      "rb") as f:
                self._RSS_SITE_GRAP_CONF = pickle.load(f).get("conf")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def get_checkin_conf(self):
        return self._SITE_CHECKIN_XPATH

    def get_subtitle_conf(self):
        return self._SITE_SUBTITLE_XPATH

    def get_login_conf(self):
        return self._SITE_LOGIN_XPATH

    def get_grap_conf(self, url=None):
        if not url:
            return self._RSS_SITE_GRAP_CONF
        for k, v in self._RSS_SITE_GRAP_CONF.items():
            if StringUtils.url_equal(k, url):
                return v
        return {}

    def get_tid_and_url(self, torrent_url):
        for key in self.URL_DETAIL_TEMPLATES:
            if key in torrent_url:
                if key == 'star-space':
                    tid = re.findall(r'tid=(\d+)', torrent_url)[0] or ""
                else:
                    tid = re.findall(r'\d+', torrent_url)[0] or ""
                    
                split_url = urlsplit(torrent_url)
                base_url = f"{split_url.scheme}://{split_url.netloc}"
                return f"{base_url}{self.URL_DETAIL_TEMPLATES[key].format(tid=tid)}"
        
        return torrent_url  # 如果不匹配任何 key，返回原始 URL

    def check_torrent_attr(self, torrent_url, cookie, ua=None, headers=None, proxy=False):
        """
        检验种子是否免费，当前做种人数
        :param torrent_url: 种子的详情页面
        :param cookie: 站点的Cookie
        :param ua: 站点的ua
        :param ua: 站点的请求头
        :param proxy: 是否使用代理
        :return: 种子属性，包含FREE 2XFREE HR PEER_COUNT等属性
        """
        ret_attr = {
            "free": False,
            "2xfree": False,
            "hr": False,
            "peer_count": 0,
            "pubdate": None
        }
        try:
            if headers and headers.get("authorization"):
                headers.pop('authorization')
            # 这里headers必须是string类型
            headers = json.dumps(headers)
            if 'm-team' in torrent_url:
                base_url = MT_URL
                detail_url = f"{base_url}/api/torrent/detail"
                res = re.findall(r'\d+', torrent_url)
                param = res[0]

                json_text = self.__get_site_page_html(url=detail_url,
                                                      cookie="",
                                                      ua=ua,
                                                      headers=headers,
                                                      proxy=proxy,
                                                      param=param)
                if not json_text:
                    logger.debug(f'获取 M-Team 明细数据失败，种子id: {param}')
                    return ret_attr
                json_data = json.loads(json_text)
                if json_data.get('message') != "SUCCESS":
                    return ret_attr
                discount = json_data.get('data').get('status').get('discount')
                seeders = json_data.get('data').get('status').get('seeders')
                if discount == 'FREE':
                    ret_attr["free"] = True
                ret_attr['peer_count'] = int(seeders)
            else:
                if not torrent_url:
                    return ret_attr
                xpath_strs = self.get_grap_conf(torrent_url)
                if not xpath_strs:
                    return ret_attr
                # 获取真实的种子详情url
                torrent_url = self.get_tid_and_url(torrent_url)

                site_info = Sites().get_sites(siteurl=torrent_url)
                html_text = self.__get_site_page_html(url=torrent_url,
                                                      cookie=cookie,
                                                      ua=ua,
                                                      headers=headers,
                                                      render=site_info.get('chrome'),
                                                      proxy=proxy)
                if not html_text:
                    return ret_attr
                if JsonUtils.is_valid_json(html_text):
                    # 检测2XFREE
                    for xpath_str in xpath_strs.get("2XFREE"):
                        name = JsonUtils.get_json_object(
                            html_text, xpath_str.split('=')[0])
                        if name == xpath_str.split('=')[1]:
                            ret_attr["free"] = True
                            ret_attr["2xfree"] = True

                    # 检测FREE
                    for xpath_str in xpath_strs.get("FREE"):
                        name = JsonUtils.get_json_object(
                            html_text, xpath_str.split('=')[0])
                        if name == xpath_str.split('=')[1]:
                            ret_attr["free"] = True

                    # 检测HR
                    for xpath_str in xpath_strs.get("HR"):
                        if JsonUtils.get_json_object(html_text, xpath_str):
                            ret_attr["hr"] = True

                    # 检测PEER_COUNT当前做种人数
                    for xpath_str in xpath_strs.get("PEER_COUNT"):
                        peer_count = JsonUtils.get_json_object(
                            html_text, xpath_str)
                        ret_attr["peer_count"] = int(
                            peer_count) if len(str(peer_count)) > 0 else 0
                else:
                    html = etree.HTML(html_text)
                    # 检测2XFREE
                    for xpath_str in xpath_strs.get("2XFREE"):
                        if html.xpath(xpath_str):
                            ret_attr["free"] = True
                            ret_attr["2xfree"] = True
                    # 检测FREE
                    for xpath_str in xpath_strs.get("FREE"):
                        if html.xpath(xpath_str):
                            ret_attr["free"] = True
                    # 检测HR
                    for xpath_str in xpath_strs.get("HR"):
                        if html.xpath(xpath_str):
                            ret_attr["hr"] = True
                    # 检测PEER_COUNT当前做种人数
                    for xpath_str in xpath_strs.get("PEER_COUNT"):
                        peer_count_dom = html.xpath(xpath_str)
                        if peer_count_dom:
                            peer_count_str = ''.join(
                                peer_count_dom[0].itertext())
                            peer_count_digit_str = ""
                            for m in peer_count_str.strip():
                                if m.isdigit():
                                    peer_count_digit_str = peer_count_digit_str + m
                                if m == " ":
                                    break
                            ret_attr["peer_count"] = int(peer_count_digit_str) if len(
                                peer_count_digit_str) > 0 else 0

                    # 检测发布时间
                    pubdate_xpath = xpath_strs.get("PUBDATE") or []
                    for xpath_str in pubdate_xpath:
                        if html.xpath(xpath_str):
                            ret_attr["pubdate"] = html.xpath(xpath_str)[0]

        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        # 随机休眼后再返回
        time.sleep(round(random.uniform(2, 8), 1))
        return ret_attr

    @staticmethod
    @lru_cache(maxsize=128)
    def __get_site_page_html(url, cookie, ua, headers=None, render=False, proxy=False, param=None):
        if JsonUtils.is_valid_json(headers):
            headers = json.loads(headers)
        else:
            headers = {}
        chrome = DrissionPageHelper()
        if render and chrome.get_status():
            # 开渲染
            html_text = chrome.get_page_html(url=url, cookies=cookie)
            if html_text:
                return html_text

        elif 'm-team' in url:
            param = {'id': param}
            headers.update({
                "contentType": 'application/json;charset=UTF-8'
            })
            if headers.get('authorization'):
                headers.pop('authorization')
            res = RequestUtils(
                headers=headers,
                proxies=Config().get_proxies() if proxy else None
            ).post_res(url=url, data=param)
            if res and res.status_code == 200:
                res.encoding = res.apparent_encoding
                return res.text
        else:
            res = RequestUtils(
                cookies=cookie,
                headers=headers,
                proxies=Config().get_proxies() if proxy else None
            ).get_res(url=url)
            if res and res.status_code == 200:
                res.encoding = res.apparent_encoding
                return res.text
        return ""
