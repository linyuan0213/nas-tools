# -*- coding: utf-8 -*-
import re

from lxml import etree

import log
from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import StringUtils
from app.utils.exception_utils import ExceptionUtils
from app.utils.types import SiteSchema


class FireFlySiteUserInfo(_ISiteUserInfo):
    schema = SiteSchema.FireFly
    order = SITE_BASE_ORDER + 51

    _brief_page = "p_index/index.php"
    _user_detail_page = "p_user/user_detail.php?uid="
    _user_traffic_page = "p_index/index.php"
    _torrent_seeding_page = "p_torrent/torrent_user.php?pop=8&uid="

    @classmethod
    def match(cls, html_text):
        """
        使用FireFly解析
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return False

        printable_text = html.xpath("string(.)") if html else ""
        return 'Powered by FireFly' in printable_text

    def _parse_site_page(self, html_text):
        html_text = self._prepare_html_text(html_text)

        user_detail = re.search(r"p_user/user_detail.php\?uid=(\d+)", html_text)
        if user_detail and user_detail.group().strip():
            self._user_detail_page = user_detail.group().strip().lstrip('/')
            self.userid = user_detail.group(1)
            self._torrent_seeding_page = f"p_torrent/torrent_user.php?pop=8&uid={self.userid}"

    def _parse_message_unread(self, html_text):
        """
        解析未读短消息数量
        :param html_text:
        :return:
        """
        pass

    def _parse_user_base_info(self, html_text):
        # 合并解析，减少额外请求调用
        self.__parse_user_traffic_info(html_text)
        self._user_traffic_page = None

        self._parse_message_unread(html_text)

        html = etree.HTML(html_text)
        if not html:
            return

        ret = html.xpath(f'//a[contains(@href, "user_detail") and contains(@href, "{self.userid}")]/span/text()')
        if ret:
            self.username = str(ret[0])
            return

    def __parse_user_traffic_info(self, html_text):
        html_text = self._prepare_html_text(html_text)
        upload_match = re.search(r"上传?[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+[KMGTPI]*)", html_text,
                                 re.IGNORECASE)
        self.upload = StringUtils.num_filesize(f"{upload_match.group(1).strip()}B") if upload_match else 0
        download_match = re.search(r"下载?[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+[KMGTPI]*)", html_text,
                                   re.IGNORECASE)
        self.download = StringUtils.num_filesize(f"{download_match.group(1).strip()}B") if download_match else 0
        ratio_match = re.search(r"分享率[:：_<>/a-zA-Z-=\"'\s#;]+([\d,.\s]+)", html_text)
        # 计算分享率
        calc_ratio = 0.0 if self.download <= 0.0 else round(self.upload / self.download, 3)
        # 优先使用页面上的分享率
        self.ratio = StringUtils.str_float(ratio_match.group(1)) if (
                ratio_match and ratio_match.group(1).strip()) else calc_ratio
        leeching_match = re.search(r"(下载数)[\u4E00-\u9FA5\D\s]+(\d+)[\s\S]+<", html_text)
        self.leeching = StringUtils.str_int(leeching_match.group(2)) if leeching_match and leeching_match.group(
            2).strip() else 0
        html = etree.HTML(html_text)
        tmps = html.xpath('//a[contains(@href,"bonus_hour")]/text()') if html else None
        if tmps:
            bonus_text = str(tmps[0]).strip()
            bonus_match = re.search(r"([\d,.]+)", bonus_text)
            if bonus_match and bonus_match.group(1).strip():
                self.bonus = StringUtils.str_float(bonus_match.group(1))
                return

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
        html = etree.HTML(str(html_text).replace(r'\/', '/'))
        if not html:
            return None

        size_col = 3
        seeders_col = 4
        # 搜索size列
        size_col_xpath = '//tr[position()=1]/th[text()="体积"]'
        if html.xpath(size_col_xpath):
            size_col = len(html.xpath(f'{size_col_xpath}/preceding-sibling::th')) + 1

        page_seeding = 0
        page_seeding_size = 0
        page_seeding_info = []
        seeding_sizes = html.xpath(f'//table[@id="table_tm"]//tr[position()>1]/td[{size_col}]')

        if seeding_sizes:
            page_seeding = len(seeding_sizes)

            for i in range(0, len(seeding_sizes)):
                size = StringUtils.num_filesize(f'{seeding_sizes[i].xpath("string(.)").strip()}B')
                seeders = 0

                page_seeding_size += size
                page_seeding_info.append([seeders, size])

        self.seeding += page_seeding
        self.seeding_size += page_seeding_size
        self.seeding_info.extend(page_seeding_info)

        # 是否存在下页数据
        next_page = None
        next_page_text = html.xpath('//a[contains(.//text(), "下一页")]/@href')
        if next_page_text:
            next_page = next_page_text[-1].strip()
            # fix up page url
            if self.userid not in next_page:
                next_page = f'{next_page}&userid={self.userid}'

        return next_page

    def _parse_user_detail_info(self, html_text):
        """
        解析用户额外信息，加入时间，等级
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return

        self.__get_user_level(html)

        # 加入日期
        join_at_text = html.xpath(
            '//tr/td[text()="加入日期" or text()="注册日期" or *[text()="加入日期"]]/following-sibling::td[1]//text()'
            '|//div/b[text()="加入日期"]/../text()')
        if join_at_text:
            self.join_at = StringUtils.unify_datetime_str(join_at_text[0].split(' (')[0].strip())


    def __get_user_level(self, html):
        role_dict = {
            'class1': 'User',
            'class2': 'Power User',
            'class3': 'Elite User',
            'class4': 'Crazy User',
            'class5': 'Insane User',
            'class6': 'Veteran User',
            'class7': 'Extreme User',
            'class8': 'Ultimate User',
            'class9': 'Master User',
            'class10': 'Star User',
            'class11': 'God User'
        }
        # 等级 获取同一行等级数据，图片格式等级，取title信息，否则取文本信息
        user_levels_attr = html.xpath('//tr/td[text()="用户等级"]/'
                                      'following-sibling::td[1]/img[1]/@alt')
        if user_levels_attr:
            self.user_level = role_dict.get(user_levels_attr[0].strip())
            return

    def _parse_message_unread_links(self, html_text, msg_links):
        pass

    def _parse_message_content(self, html_text):
        pass
