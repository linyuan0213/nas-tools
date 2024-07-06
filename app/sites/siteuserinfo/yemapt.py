# -*- coding: utf-8 -*-
from datetime import datetime, timezone
import json
import base64

from urllib.parse import urljoin

import pytz

from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import RequestUtils, JsonUtils
from app.utils.types import SiteSchema
from config import Config


class YemaPTUserInfo(_ISiteUserInfo):
    schema = SiteSchema.YemaPT
    order = SITE_BASE_ORDER + 16

    @classmethod
    def match(cls, html_text):
        return "YemaPT" in html_text

    def parse(self):
        """
        解析站点信息
        :return:
        """
        self._parse_favicon(self._index_html)
        if not self._parse_logged_in(self._index_html):
            return

        self._parse_site_page(self._index_html)
        self._parse_user_base_info(self._index_html)
        self._pase_unread_msgs()
        self._parse_user_traffic_info(self._index_html)
        self._parse_user_detail_info(self._index_html)

        self._parse_seeding_pages()
        self.seeding_info = json.dumps(self.seeding_info)

    def _parse_favicon(self, html_text):
        """
        解析站点favicon,返回base64 fav图标
        :param html_text:
        :return:
        """
        self._favicon_url = 'https://static-c.yemapt.org/icons/icons8-mustang-32.png'

        res = RequestUtils(cookies=self._site_cookie, session=self._session, headers=self._site_headers, timeout=60).get_res(
            url=self._favicon_url)
        if res:
            self.site_favicon = base64.b64encode(res.content).decode()

    def _parse_user_base_info(self, html_text):
        if not JsonUtils.is_valid_json(html_text):
            return

        json_data = json.loads(html_text)
        if json_data.get('success') and json_data.get('data'):
            self.username = json_data.get('data').get('name')
            self.bonus = json_data.get('data').get('bonus')
            self._torrent_seeding_page = '/api/torrent/fetchUserTorrentList'
            self._torrent_seeding_params = {"status":"seeding","pageParam":{"current":1,"pageSize":40,"pageSizeOptions":["10","20","40"]}}

    def _parse_site_page(self, html_text):
        pass

    def _parse_user_detail_info(self, html_text):
        """
        解析用户额外信息，加入时间，等级
        :param html_text:
        :return:
        """
        role_dict = {
            0: 'level0/乱民',
            1: 'level1/小卒',
            2: 'level2/教喻',
            3: 'level3/登仕郎',
            4: 'level4/修职郎',
            5: 'level5/文林郎',
            6: 'level6/忠武校尉',
            7: 'level7/承信将军',
            8: 'level8/武毅将军',
            9: 'level9/武节将军',
            10: 'level10/显威将军',
            11: 'level11/宣武将军',
            12: 'level12/定远将军',
            13: 'level13/昭毅将军',
            14: 'level14/定国将军',
            15: 'level15/金吾将军',
            16: 'level16/光禄大夫',
            17: 'level17/特近光禄大夫'
        }
        if not JsonUtils.is_valid_json(html_text):
            return
        json_data = json.loads(html_text)
        if json_data.get('data') is not None:
            # 用户等级
            level_num = json_data.get('data').get('level')
            self.user_level = role_dict.get(level_num, '其他')

            # 加入日期
            org_date = json_data.get('data').get('registerTime')
            dt_utc = datetime.fromisoformat(org_date.replace('Z', '+00:00'))

            local_tz = pytz.timezone(Config().get_timezone())
            local_date = dt_utc.astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
            self.join_at = local_date

    def _parse_user_traffic_info(self, html_text):
        json_data = json.loads(html_text)
        if json_data.get('data') is not None:
            self.upload = int(json_data.get('data').get('promotionUploadSize'))

            self.download = int(json_data.get('data').get('promotionDownloadSize'))

            self.ratio = 0 if self.download <= 0 else round(self.upload / self.download, 3)

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):

        if not JsonUtils.is_valid_json(html_text):
            return None

        json_data = json.loads(html_text)

        page_seeding = 0
        page_seeding_size = 0
        page_seeding_info = []
        next_page = None

        if json_data.get('data'):
            page_seeding = len(json_data.get('data'))
            for data in json_data.get('data'):
                # 暂时无法获取
                size = int(data.get('fileSize'))
                seeders = 0

                page_seeding_size += size
                page_seeding_info.append([seeders, size])

            self.seeding += page_seeding
            self.seeding_size += page_seeding_size
            self.seeding_info.extend(page_seeding_info)

            page_num = self._torrent_seeding_params.get('pageParam').get('current')
            next_page = page_num + 1
            self._torrent_seeding_params['pageParam']['current'] = next_page
        return next_page

    def _get_page_content(self, url, params=None, headers=None):
        """
        :param url: 网页地址
        :param params: post参数
        :param headers: 额外的请求头
        :return:
        """
        req_headers = None
        proxies = Config().get_proxies() if self._proxy else None
        if self._ua or headers or self._addition_headers:
            req_headers = {}
            if headers:
                req_headers.update(headers)

            if isinstance(self._ua, str):
                req_headers.update({
                    "Content-Type": "application/json",
                    "User-Agent": f"{self._ua}"
                })
            else:
                req_headers.update(self._ua)

            if self._addition_headers:
                req_headers.update(self._addition_headers)

        params = json.dumps(params, separators=(',', ':'))
        res = RequestUtils(cookies=self._site_cookie,
                            session=self._session,
                            proxies=proxies,
                            headers=req_headers).post_res(url=url, data=params)
        if res is not None and res.status_code in (200, 500, 403):
            if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                res.encoding = "UTF-8"
            else:
                res.encoding = res.apparent_encoding
            return res.text

        return ""

    def _parse_seeding_pages(self):
        if self._torrent_seeding_page:
            # 第一页
            next_page = self._parse_user_torrent_seeding_info(
                self._get_page_content(urljoin(self._base_url, self._torrent_seeding_page),
                                       self._torrent_seeding_params,
                                       self._site_headers))

            # 其他页处理
            while next_page:
                next_page = self._parse_user_torrent_seeding_info(
                    self._get_page_content(urljoin(self._base_url, self._torrent_seeding_page),
                                           self._torrent_seeding_params,
                                           self._site_headers),
                    multi_page=True)

    def _parse_message_unread_links(self, html_text, msg_links):
        return None

    def _parse_message_content(self, html_text):
        return None, None, None
