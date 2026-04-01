# -*- coding: utf-8 -*-
import json
from urllib.parse import urljoin
from typing import Optional, Tuple

from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import RequestUtils, StringUtils, JsonUtils
from app.utils.types import SiteSchema
from config import Config


class RousiSiteUserInfo(_ISiteUserInfo):
    """
    Rousi.pro 站点解析器
    使用 API v1 接口，通过 Passkey (Bearer Token) 进行认证
    """
    schema = SiteSchema.RousiPro
    order = SITE_BASE_ORDER + 20

    @classmethod
    def match(cls, html_text):
        """
        是否匹配当前解析模型
        Rousi.pro 通过检测特定内容来判断
        """
        # 简单检测是否包含Rousi相关特征
        return "rousi" in html_text.lower()

    def parse(self):
        """
        重写parse方法，因为Rousi使用API接口，不需要传统的页面解析流程
        """
        self._parse_favicon(self._index_html)
        if not self._parse_logged_in(self._index_html):
            return

        self._parse_site_page(self._index_html)
        self._parse_user_base_info(self._index_html)
        self._pase_unread_msgs()
        # Rousi API在base info中已包含流量信息，不需要额外解析
        self._parse_user_detail_info(self._index_html)

        # 做种信息解析
        self._parse_seeding_pages()
        self.seeding_info = json.dumps(self.seeding_info)

    def _parse_site_page(self, html_text):
        """
        配置 API 请求地址和请求头
        使用 API v1 的 /profile 接口获取用户信息
        """
        self._base_url = f"https://{StringUtils.get_url_domain(self.site_url)}"
        self._user_basic_page = "api/v1/profile?include_fields[user]=seeding_leeching_data"
        
        # 设置API请求头
        if self._site_headers and any(k.lower() == "authorization" for k in self._site_headers):
            # 如果已有Authorization头（不区分大小写），直接使用
            pass
        else:
            # 尝试从cookie或其它地方提取token
            token = self._extract_token()
            if token:
                if not self._site_headers:
                    self._site_headers = {}
                self._site_headers["Authorization"] = f"{token}"
        
        # 确保有必要的headers
        if not self._site_headers:
            self._site_headers = {}
        
        # 添加JSON相关的headers
        self._site_headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        
        # Rousi.pro API v1 在单个接口返回所有信息，无需额外页面
        self._user_traffic_page = None
        self._user_detail_page = None
        self._torrent_seeding_page = None
        self._user_mail_unread_page = None
        self._sys_mail_unread_page = None

    def _parse_logged_in(self, html_text):
        """
        判断是否登录成功
        API 认证模式下，通过检查是否有有效的Authorization头来判断
        """
        token = self._extract_token()
        if not token:
            self.err_msg = "未检测到有效的Authorization头"
            return False
        return True

    def _parse_user_base_info(self, html_text):
        """
        解析用户基本信息
        通过 API v1 接口获取用户完整信息，包括上传下载量、做种数据等

        API 响应示例：
        {
            "code": 0,
            "message": "success",
            "data": {
                "id": 1,
                "username": "example",
                "level_text": "Lv.5",
                "registered_at": "2024-01-01T00:00:00Z",
                "uploaded": 1073741824,
                "downloaded": 536870912,
                "ratio": 2.0,
                "karma": 1000.5,
                "seeding_leeching_data": {
                    "seeding_count": 10,
                    "seeding_size": 10737418240,
                    "leeching_count": 2,
                    "leeching_size": 2147483648
                }
            }
        }
        """
        # 获取API数据
        api_url = urljoin(self._base_url, self._user_basic_page)
        api_response = self._get_page_content(api_url, headers=self._site_headers)
        
        if not api_response or not JsonUtils.is_valid_json(api_response):
            self.err_msg = "API请求失败或返回无效JSON"
            return

        try:
            data = json.loads(api_response)
        except json.JSONDecodeError:
            self.err_msg = "JSON解析失败"
            return

        if not data or data.get("code") != 0:
            self.err_msg = data.get("message", "未知错误")
            return

        user_info = data.get("data")
        if not user_info:
            return

        # 基本信息
        self.userid = user_info.get("id")
        self.username = user_info.get("username")
        self.user_level = user_info.get("level_text") or user_info.get("role_text")

        # 注册时间：统一格式为 YYYY-MM-DD HH:MM:SS
        join_at = StringUtils.unify_datetime_str(user_info.get("registered_at"))
        if join_at:
            # 确保格式为 YYYY-MM-DD HH:MM:SS (19位)
            if len(join_at) >= 19:
                self.join_at = join_at[:19]
            else:
                self.join_at = join_at

        # 流量信息
        self.upload = int(user_info.get("uploaded") or 0)
        self.download = int(user_info.get("downloaded") or 0)
        self.ratio = round(float(user_info.get("ratio") or 0), 2)

        # 魔力值（站点称为 karma）
        self.bonus = float(user_info.get("karma") or 0)

        # 做种/下载中数据
        sl_data = user_info.get("seeding_leeching_data", {})
        self.seeding = int(sl_data.get("seeding_count") or 0)
        self.seeding_size = int(sl_data.get("seeding_size") or 0)
        self.leeching = int(sl_data.get("leeching_count") or 0)
        self.leeching_size = int(sl_data.get("leeching_size") or 0)

    def _parse_user_traffic_info(self, html_text):
        """
        解析用户流量信息
        Rousi.pro API v1 在 _parse_user_base_info 中已完成所有解析，此方法无需实现
        """
        pass

    def _parse_user_detail_info(self, html_text):
        """
        解析用户详细信息
        Rousi.pro API v1 在 _parse_user_base_info 中已完成所有解析，此方法无需实现
        """
        pass

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        解析用户做种信息
        Rousi.pro API v1 在 _parse_user_base_info 中已通过 seeding_leeching_data 获取做种数据
        无需额外解析做种列表

        :param html_text: 页面内容
        :param multi_page: 是否多页数据
        :return: 下页地址（无下页返回 None）
        """
        return None

    def _parse_message_unread_links(self, html_text, msg_links):
        """
        解析未读消息链接
        Rousi.pro API v1 暂未提供消息相关接口

        :param html_text: 页面内容
        :param msg_links: 消息链接列表
        :return: 下页地址（无下页返回 None）
        """
        return None

    def _parse_message_content(self, html_text):
        """
        解析消息内容
        Rousi.pro API v1 暂未提供消息相关接口

        :param html_text: 页面内容
        :return: (标题, 日期, 内容)
        """
        return None, None, None

    def _pase_unread_msgs(self):
        """
        解析所有未读消息标题和内容
        Rousi.pro API v1 暂未提供消息相关接口，暂时以网页接口实现
        
        :return:
        """
        token = self._extract_token()
        if not token:
            return
        
        headers = {
            "User-Agent": self._ua if isinstance(self._ua, str) else "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"
        }
        
        def __get_message_list(page: int):
            params = {
                "page": page,
                "page_size": 100,
                "unread_only": "true"
            }
            res = RequestUtils(
                headers=headers,
                timeout=60,
                proxies=Config().get_proxies() if self._proxy else None
            ).get_res(
                url=urljoin(self._base_url, "api/messages"),
                params=params
            )
            if not res or res.status_code != 200:
                return {
                    "messages": [],
                    "total_pages": 0
                }
            
            try:
                response_data = res.json()
                if response_data.get("code", -1) != 0:
                    return {
                        "messages": [],
                        "total_pages": 0
                    }
                return response_data.get("data", {})
            except:
                return {
                    "messages": [],
                    "total_pages": 0
                }
        
        # 分页获取所有未读消息
        page = 0
        res = __get_message_list(page)
        page += 1
        messages = res.get("messages", [])
        total_pages = res.get("total_pages", 0)
        while page < total_pages:
            res = __get_message_list(page)
            messages.extend(res.get("messages", []))
            page += 1
        
        self.message_unread = len(messages)
        for message in messages:
            head = message.get("title")
            date = StringUtils.unify_datetime_str(message.get("created_at"))
            content = message.get("content")
            self.message_unread_contents.append((head, date, content))
            
        # 更新消息为已读
        if messages:
            RequestUtils(
                headers=headers,
                timeout=60,
                proxies=Config().get_proxies() if self._proxy else None
            ).post_res(
                url=urljoin(self._base_url, "api/messages/read-all")
            )

    # 辅助方法
    def _extract_token(self):
        """
        从站点headers或cookie中提取API Token
        """
        # 从headers中提取
        if self._site_headers and isinstance(self._site_headers, dict):
            auth = self._site_headers.get("Authorization", "") or self._site_headers.get("authorization", "")
            if auth.startswith("Bearer "):
                return auth
            elif auth:
                return f"Bearer {auth}"
        
        # 从cookie中提取（如果token存储在cookie中）
        if self._site_cookie and "token=" in self._site_cookie:
            # 简单提取，实际可能需要解析cookie字符串
            import re
            match = re.search(r'token=([^;]+)', self._site_cookie)
            if match:
                return f"Bearer {match.group(1)}"
        
        return None