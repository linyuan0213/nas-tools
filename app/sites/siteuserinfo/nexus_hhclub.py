# -*- coding: utf-8 -*-
import re

from lxml import etree

import log
import json

from urllib.parse import urljoin
from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import StringUtils, JsonUtils
from app.utils.exception_utils import ExceptionUtils
from app.utils.types import SiteSchema


class NexusPhpHhclubSiteUserInfo(_ISiteUserInfo):
    schema = SiteSchema.HHCLUB
    order = SITE_BASE_ORDER + 5

    userdetails_page = ''

    @classmethod
    def match(cls, html_text):
        """
        默认使用NexusPhp解析
        :param html_text:
        :return:
        """
        return 'HHCLUB' in html_text

    def parse(self):
        """
        解析站点信息
        :return:
        """
        self._parse_favicon(self._index_html)
        if not self._parse_logged_in(self._index_html):
            return

        self._parse_site_page(self._index_html)
        self._parse_user_base_info(self.userdetails_page)
        self._pase_unread_msgs()
        self._parse_user_traffic_info(self.userdetails_page)
        self._parse_user_detail_info(self.userdetails_page)

        self._parse_seeding_pages()
        self.seeding_info = json.dumps(self.seeding_info)

    def _parse_site_page(self, html_text):
        html_text = self._prepare_html_text(html_text)

        user_detail = re.search(r"userdetails.php\?id=(\d+)", html_text)
        if user_detail and user_detail.group().strip():
            self._user_detail_page = user_detail.group().strip().lstrip('/')
            self.userid = user_detail.group(1)
            self._torrent_seeding_page = f"getusertorrentlistajax.php?userid={self.userid}&type=seeding&ajax=1"
        else:
            user_detail = re.search(r"(userdetails)", html_text)
            if user_detail and user_detail.group().strip():
                self._user_detail_page = user_detail.group().strip().lstrip('/')
                self.userid = None
                self._torrent_seeding_page = None
        detail_page_url = f'{self._base_url}/{self._user_detail_page}'
        self.userdetails_page = self._get_page_content(url=detail_page_url)

    def _parse_message_unread(self, html_text):
        """
        解析未读短消息数量
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return

        message_labels = html.xpath('//a[@href="messages.php"]/..')
        message_labels.extend(html.xpath('//a[contains(@href, "messages.php")]/..'))
        if message_labels:
            message_text = message_labels[0].xpath("string(.)")

            log.debug(f"【Sites】{self.site_name} 消息原始信息 {message_text}")
            message_unread_match = re.findall(r"[^Date](信息箱\s*|\(|你有\xa0)(\d+)", message_text)

            if message_unread_match and len(message_unread_match[-1]) == 2:
                self.message_unread = StringUtils.str_int(message_unread_match[-1][1])
            elif message_text.isdigit():
                self.message_unread = StringUtils.str_int(message_text)

    def _parse_user_base_info(self, html_text):
        # 合并解析，减少额外请求调用
        self.__parse_user_traffic_info(html_text)

        html = etree.HTML(html_text)
        if not html:
            return

        ret = html.xpath(f'//a[contains(@href, "userdetails") and contains(@href, "{self.userid}")]//b//text()')
        if ret:
            self.username = str(ret[0])
            return

    def __parse_user_traffic_info(self, html_text):
        html_text = self._prepare_html_text(html_text)

        html = etree.HTML(html_text)

        upload_match = html.xpath('//span[contains(text(), "上传量")]/following-sibling::span')
        self.upload = StringUtils.num_filesize(upload_match[0].text) if upload_match else 0
        download_match = html.xpath('//span[contains(text(), "下载量")]/following-sibling::span')
        self.download = StringUtils.num_filesize(download_match[0].text) if download_match else 0
        ratio_match = html.xpath('//span[contains(text(), "分享率")]/following-sibling::span')
        # 计算分享率
        calc_ratio = 0.0 if self.download <= 0.0 else round(self.upload / self.download, 3)
        # 优先使用页面上的分享率
        self.ratio = StringUtils.str_float(ratio_match[0].xpath('string(*)')) if ratio_match else calc_ratio
        self.leeching = 0
        tmps = ''.join(html.xpath('//span[contains(text(), "憨豆")]/following-sibling::div/text()'))
        if tmps:
            bonus_text = tmps.strip()
            bonus_match = re.search(r"([\d,.]+)", bonus_text)
            if bonus_match and bonus_match.group(1).strip():
                self.bonus = StringUtils.str_float(bonus_match.group(1))
                return
        try:
            if bonus_match and bonus_match.group(1).strip():
                self.bonus = StringUtils.str_float(bonus_match.group(1))
                return
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

    def _parse_user_traffic_info(self, html_text):
        """
        上传/下载/分享率 [做种数/魔力值]
        :param html_text:
        :return:
        """
        pass

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """

        if not JsonUtils.is_valid_json(html_text):
            return None

        json_data = json.loads(html_text)

        page_seeding = 0
        page_seeding_size = 0
        page_seeding_info = []

        seeding_torrents = json_data.get('data')
        if seeding_torrents:
            page_seeding = len(seeding_torrents)

            for torrent in seeding_torrents:
                size = StringUtils.num_filesize(torrent.get('size'))
                seeders = int(torrent.get('seeders'))

                page_seeding_size += size
                page_seeding_info.append([seeders, size])
        else:
            return seeding_torrents

        self.seeding += page_seeding
        self.seeding_size += page_seeding_size
        self.seeding_info.extend(page_seeding_info)

        # 是否存在下页数据

        return seeding_torrents

    def _parse_seeding_pages(self):
        if self._torrent_seeding_page:
            # 第一页
            page_num = 0
            while True:
                self._torrent_seeding_page = f'{self._torrent_seeding_page}&page={page_num}'
                data = self._parse_user_torrent_seeding_info(
                    self._get_page_content(urljoin(self._base_url, self._torrent_seeding_page),
                                           self._torrent_seeding_params,
                                           self._site_headers)
                   )
                page_num = page_num + 1
                if not data:
                    break

    def _parse_user_detail_info(self, html_text):
        """
        解析用户额外信息，加入时间，等级
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return

        user_levels_text = html.xpath('//span[contains(text(), "等级")]/following-sibling::span/b/text()')
        if user_levels_text:
            self.user_level = user_levels_text[0].strip()
        # 加入日期
        join_at_text = html.xpath('//span[contains(text(), "加入日期")]/following-sibling::span/span/@title')
        if join_at_text:
            self.join_at = StringUtils.unify_datetime_str(join_at_text[0].split(' (')[0].strip())

    def _parse_message_unread_links(self, html_text, msg_links):
        """
        获取未阅读消息链接
        :param html_text:
        :return:
        """
        pass

    def _parse_message_content(self, html_text):
        """
        解析短消息内容
        :param html_text:
        :return:  head: message, date: time, content: message content
        """
        pass
