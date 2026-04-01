import json
import re
import time
from datetime import datetime
from enum import Enum

import log
from jinja2 import Environment, BaseLoader
from app.conf import ModuleConf
from app.helper import DbHelper, SubmoduleHelper
from app.message.message_center import MessageCenter
from app.utils import StringUtils, ExceptionUtils
from app.utils.commons import SingletonMeta
from app.utils.types import SearchType, MediaType
from config import Config
from web.backend.web_utils import WebUtils


def _filesize_filter(value):
    """Jinja2 filter: 格式化文件大小"""
    if value is None:
        return ''
    return StringUtils.str_filesize(value) if value else ''


def _datetime_filter(value, format_str='%Y-%m-%d %H:%M:%S'):
    """Jinja2 filter: 格式化日期时间"""
    if not value:
        return ''
    if isinstance(value, (int, float)):
        return time.strftime(format_str, time.localtime(value))
    if isinstance(value, str):
        # 尝试解析时间戳
        try:
            timestamp = float(value)
            return time.strftime(format_str, time.localtime(timestamp))
        except (ValueError, TypeError):
            return value
    return str(value)


def _default_filter(value, default_value=''):
    """Jinja2 filter: 默认值处理"""
    if value is None or value == '':
        return default_value
    return value


def _yesno_filter(value, yes='是', no='否'):
    """Jinja2 filter: 布尔值转换为是/否"""
    if value is True:
        return yes
    elif value is False:
        return no
    return no


def _truncatestr_filter(value, length=100, suffix='...'):
    """Jinja2 filter: 截断字符串"""
    if not value:
        return ''
    value = str(value)
    if len(value) <= length:
        return value
    return value[:length - len(suffix)] + suffix


def _striptags_filter(value):
    """Jinja2 filter: 去除HTML标签"""
    if not value:
        return ''
    return re.sub(r'<[^>]+>', '', str(value))


class Message(metaclass=SingletonMeta):
    dbhelper = None
    messagecenter = None
    _message_schemas = []
    _active_clients = []
    _active_interactive_clients = {}
    _client_configs = {}
    _domain = None

    def __init__(self):
        self._message_schemas = SubmoduleHelper.import_submodules(
            'app.message.client',
            filter_func=lambda _, obj: hasattr(obj, 'schema')
        )
        log.debug(f"【Message】加载消息服务：{self._message_schemas}")
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()
        self.messagecenter = MessageCenter()
        self._domain = Config().get_domain()
        # 停止旧服务
        if self._active_clients:
            for active_client in self._active_clients:
                if active_client.get("search_type") in self.get_search_types():
                    client = active_client.get("client")
                    if client and hasattr(client, "stop_service"):
                        client.stop_service()
        # 活跃的客户端
        self._active_clients = []
        # 活跃的交互客户端
        self._active_interactive_clients = {}
        # 全量客户端配置
        self._client_configs = {}
        for client_config in self.dbhelper.get_message_client() or []:
            config = json.loads(client_config.CONFIG) if client_config.CONFIG else {}
            config.update({
                "interactive": client_config.INTERACTIVE
            })
            templates = {}
            if client_config.TEMPLATES:
                try:
                    templates = json.loads(client_config.TEMPLATES)
                except json.JSONDecodeError:
                    log.error(f"【Message】客户端 {client_config.NAME} 的模板配置不是有效的JSON: {client_config.TEMPLATES}")
                    templates = {}
            client_conf = {
                "id": client_config.ID,
                "name": client_config.NAME,
                "type": client_config.TYPE,
                "config": config,
                "switchs": json.loads(client_config.SWITCHS) if client_config.SWITCHS else [],
                "interactive": client_config.INTERACTIVE,
                "enabled": client_config.ENABLED,
                "templates": templates
            }
            self._client_configs[str(client_config.ID)] = client_conf
            if not client_config.ENABLED or not config:
                continue
            client = {
                "search_type": ModuleConf.MESSAGE_CONF.get('client').get(client_config.TYPE, {}).get('search_type'),
                "max_length": ModuleConf.MESSAGE_CONF.get('client').get(client_config.TYPE, {}).get('max_length'),
                "client": self.__build_class(ctype=client_config.TYPE, conf=config)
            }
            client.update(client_conf)
            self._active_clients.append(client)
            if client.get("interactive"):
                self._active_interactive_clients[client.get("search_type")] = client

    def __build_class(self, ctype, conf):
        for message_schema in self._message_schemas:
            try:
                if message_schema.match(ctype):
                    return message_schema(conf)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def __render_template(self, template_str, variables):
        """
        使用Jinja2渲染模板
        :param template_str: 模板字符串
        :param variables: 变量字典
        :return: 渲染后的字符串，如果渲染失败则返回None
        """
        if not template_str:
            return None
        try:
            env = Environment(loader=BaseLoader())
            # 添加自定义过滤器
            env.filters['filesize'] = _filesize_filter
            env.filters['datetime'] = _datetime_filter
            env.filters['default'] = _default_filter
            env.filters['yesno'] = _yesno_filter
            env.filters['truncatestr'] = _truncatestr_filter
            env.filters['striptags'] = _striptags_filter
            template = env.from_string(template_str)
            result = template.render(**variables)
            # 处理转义字符（JSON中的\n需要转换为实际的换行符）
            result = result.replace('\\n', '\n')
            return result
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【Message】模板渲染失败：{str(e)}")
            return None

    def __apply_client_template(self, client, msg_type, variables):
        """
        应用客户端模板
        :param client: 客户端配置
        :param msg_type: 消息类型，如 'download_start', 'transfer_finished' 等
        :param variables: 模板变量字典
        :return: (title, text) 渲染后的标题和内容，如果无模板则返回 (None, None)
        """
        client_name = client.get('name', '未知')
        templates = client.get("templates")
        
        log.debug(f"【Message】客户端 {client_name} 模板配置: {templates}")
        
        # 如果 templates 是字符串，尝试解析为 JSON
        if isinstance(templates, str):
            try:
                templates = json.loads(templates)
                log.debug(f"【Message】客户端 {client_name} 模板配置已解析为字典")
            except json.JSONDecodeError as e:
                log.error(f"【Message】客户端 {client_name} 模板配置 JSON 解析失败: {e}")
                return None, None
        
        if not templates or not isinstance(templates, dict):
            log.debug(f"【Message】客户端 {client_name} 没有模板配置或格式不正确, 类型: {type(templates)}")
            return None, None
        
        template_config = templates.get(msg_type)
        log.debug(f"【Message】客户端 {client_name} 消息类型 {msg_type} 的模板: {template_config}")
        
        if not template_config or not isinstance(template_config, dict):
            log.debug(f"【Message】客户端 {client_name} 没有 {msg_type} 类型的模板配置")
            return None, None
        
        title_template = template_config.get("title")
        text_template = template_config.get("text")
        
        log.debug(f"【Message】客户端 {client_name} 标题模板: {title_template}")
        log.debug(f"【Message】客户端 {client_name} 内容模板: {text_template}")
        
        rendered_title = self.__render_template(title_template, variables) if title_template else None
        rendered_text = self.__render_template(text_template, variables) if text_template else None
        
        log.info(f"【Message】客户端 {client_name} 模板渲染结果 - 标题: {rendered_title is not None}, 内容: {rendered_text is not None}")
        
        return rendered_title, rendered_text

    def get_status(self, ctype=None, config=None):
        """
        测试消息设置状态
        """
        if not config or not ctype:
            return False
        # 测试状态不启动监听服务
        state, ret_msg = self.__build_class(ctype=ctype,
                                            conf=config).send_msg(title="测试",
                                                                  text="这是一条测试消息",
                                                                  url="https://github.com/linyuan0213/nas-tools")
        if not state:
            log.error(f"【Message】{ctype} 发送测试消息失败：%s" % ret_msg)
        return state

    def __sendmsg(self, client, title, text="", image="", url="", user_id=""):
        """
        通用消息发送
        :param client: 消息端
        :param title: 消息标题
        :param text: 消息内容
        :param image: 图片URL
        :param url: 消息跳转地址
        :param user_id: 用户ID，如有则只发给这个用户
        :return: 发送状态、错误信息
        """
        if not client or not client.get('client'):
            return None
        cname = client.get('name')
        log.info(f"【Message】发送消息 {cname}：title={title}, text={text}")
        if self._domain:
            if url:
                # 唤起App
                if '/open?url=' in url:
                    url = "%s%s" % (self._domain, url)
                # 跳转页面
                elif not url.startswith("http"):
                    url = "%s?next=%s" % (self._domain, url)
            else:
                url = ""
        else:
            url = ""
        # 消息内容分段
        max_length = client.get("max_length")
        if max_length:
            texts = StringUtils.split_text(text, max_length)
        else:
            texts = [text]
        # 循环发送
        for txt in texts:
            if not title:
                title = txt
                txt = ""
            state, ret_msg = client.get('client').send_msg(title=title,
                                                           text=txt,
                                                           image=image,
                                                           url=url,
                                                           user_id=user_id)
            title = None
            if not state:
                log.error(f"【Message】{cname} 消息发送失败：%s" % ret_msg)
                return state
        return True

    def send_channel_msg(self, channel, title, text="", image="", url="", user_id=""):
        """
        按渠道发送消息，用于消息交互
        :param channel: 消息渠道
        :param title: 消息标题
        :param text: 消息内容
        :param image: 图片URL
        :param url: 消息跳转地址
        :param user_id: 用户ID，如有则只发给这个用户
        :return: 发送状态、错误信息
        """
        # 插入消息中心
        if channel == SearchType.WEB:
            self.messagecenter.insert_system_message(title=title, content=text)
            return True
        # 发送消息
        client = self._active_interactive_clients.get(channel)
        if client:
            state = self.__sendmsg(client=client,
                                   title=title,
                                   text=text,
                                   image=image,
                                   url=url,
                                   user_id=user_id)
            return state
        return False

    def __send_list_msg(self, client, medias, user_id, title):
        """
        发送选择类消息
        """
        if not client or not client.get('client'):
            return None
        cname = client.get('name')
        log.info(f"【Message】发送消息 {cname}：title={title}")
        state, ret_msg = client.get('client').send_list_msg(medias=medias,
                                                            user_id=user_id,
                                                            title=title,
                                                            url=self._domain)
        if not state:
            log.error(f"【Message】{cname} 发送消息失败：%s" % ret_msg)
        return state

    def send_channel_list_msg(self, channel, title, medias: list, user_id=""):
        """
        发送列表选择消息，用于消息交互
        :param channel: 消息渠道
        :param title: 消息标题
        :param medias: 媒体信息列表
        :param user_id: 用户ID，如有则只发给这个用户
        :return: 发送状态、错误信息
        """
        if channel == SearchType.WEB:
            texts = []
            index = 1
            for media in medias:
                texts.append(f"{index}. {media.get_title_string()}，{media.get_vote_string()}")
                index += 1
            self.messagecenter.insert_system_message(title=title, content="\n".join(texts))
            return True
        client = self._active_interactive_clients.get(channel)
        if client:
            state = self.__send_list_msg(client=client,
                                         title=title,
                                         medias=medias,
                                         user_id=user_id)
            return state
        return False

    def send_download_message(self, in_from: SearchType, can_item, download_setting_name=None, downloader_name=None):
        """
        发送下载的消息
        :param in_from: 下载来源
        :param can_item: 下载的媒体信息
        :param download_setting_name: 下载设置名称
        :param downloader_name: 下载器名称
        :return: 发送状态、错误信息
        """
        # 默认消息
        msg_title = f"{can_item.get_title_ep_string()} 开始下载"
        msg_text = f"{can_item.get_star_string()}"
        msg_text = f"{msg_text}\n来自：{in_from.value}"
        if download_setting_name:
            msg_text = f"{msg_text}\n下载设置：{download_setting_name}"
        if downloader_name:
            msg_text = f"{msg_text}\n下载器：{downloader_name}"
        if can_item.user_name:
            msg_text = f"{msg_text}\n用户：{can_item.user_name}"
        if can_item.site:
            if in_from == SearchType.USERRSS:
                msg_text = f"{msg_text}\n任务：{can_item.site}"
            else:
                msg_text = f"{msg_text}\n站点：{can_item.site}"
        if can_item.get_resource_type_string():
            msg_text = f"{msg_text}\n质量：{can_item.get_resource_type_string()}"
        if can_item.size:
            if str(can_item.size).isdigit():
                size = StringUtils.str_filesize(can_item.size)
            else:
                size = can_item.size
            msg_text = f"{msg_text}\n大小：{size}"
        if can_item.org_string:
            msg_text = f"{msg_text}\n种子：{can_item.org_string}"
        if can_item.seeders:
            msg_text = f"{msg_text}\n做种数：{can_item.seeders}"
        msg_text = f"{msg_text}\n促销：{can_item.get_volume_factor_string()}"
        if can_item.hit_and_run:
            msg_text = f"{msg_text}\nHit&Run：是"
        if can_item.description:
            html_re = re.compile(r'<[^>]+>', re.S)
            description = html_re.sub('', can_item.description)
            can_item.description = re.sub(r'<[^>]+>', '', description)
            msg_text = f"{msg_text}\n描述：{can_item.description}"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=msg_title, content=msg_text)
        # 发送消息
        for client in self._active_clients:
            if "download_start" in client.get("switchs"):
                # 准备模板变量 - 提供更丰富的字段
                # 计算文件大小字符串
                size_str = StringUtils.str_filesize(can_item.size) if can_item.size else ''
                # 处理描述文本（去除HTML标签）
                description_clean = ''
                if can_item.description:
                    description_clean = re.sub(r'<[^>]+>', '', can_item.description)
                
                variables = {
                    "item": can_item,
                    "in_from": in_from,
                    "download_setting_name": download_setting_name or '',
                    "downloader_name": downloader_name or '',
                    # 常用字段直接暴露
                    "title": can_item.title or can_item.get_name() or '',
                    "year": can_item.year or '',
                    "season": can_item.get_season_string() if hasattr(can_item, 'get_season_string') else '',
                    "episode": can_item.get_episode_string() if hasattr(can_item, 'get_episode_string') else '',
                    "site": can_item.site or '',
                    "size": can_item.size or 0,
                    "size_str": size_str,
                    "seeders": can_item.seeders or 0,
                    "peers": can_item.peers or 0,
                    "org_string": can_item.org_string or '',
                    "description": description_clean,
                    "description_raw": can_item.description or '',
                    "resource_type": can_item.get_resource_type_string() if hasattr(can_item, 'get_resource_type_string') else '',
                    "volume_factor": can_item.get_volume_factor_string() if hasattr(can_item, 'get_volume_factor_string') else '未知',
                    "hit_and_run": can_item.hit_and_run or False,
                    "user_name": can_item.user_name or '',
                    "page_url": can_item.page_url or '',
                    "vote_average": can_item.vote_average or 0,
                    "star_string": can_item.get_star_string() if hasattr(can_item, 'get_star_string') else '',
                    "title_ep_string": can_item.get_title_ep_string() if hasattr(can_item, 'get_title_ep_string') else '',
                    "title_string": can_item.get_title_string() if hasattr(can_item, 'get_title_string') else '',
                }
                # 应用模板
                template_title, template_text = self.__apply_client_template(
                    client, "download_start", variables
                )
                # 使用模板渲染结果或默认消息
                final_title = template_title if template_title is not None else msg_title
                final_text = template_text if template_text is not None else msg_text
                self.__sendmsg(
                    client=client,
                    title=final_title,
                    text=final_text,
                    image=can_item.get_message_image(),
                    url='downloading'
                )

    def send_transfer_movie_message(self, in_from: Enum, media_info, exist_filenum, category_flag):
        """
        发送转移电影的消息
        :param in_from: 转移来源
        :param media_info: 转移的媒体信息
        :param exist_filenum: 已存在的文件数
        :param category_flag: 二级分类开关
        :return: 发送状态、错误信息
        """
        msg_title = f"{media_info.get_title_string()} 已入库"
        if media_info.vote_average:
            msg_str = f"{media_info.get_vote_string()}，类型：电影"
        else:
            msg_str = "类型：电影"
        if media_info.category:
            if category_flag:
                msg_str = f"{msg_str}，类别：{media_info.category}"
        if media_info.get_resource_type_string():
            msg_str = f"{msg_str}，质量：{media_info.get_resource_type_string()}"
        msg_str = f"{msg_str}，大小：{StringUtils.str_filesize(media_info.size)}，来自：{in_from.value}"
        if exist_filenum != 0:
            msg_str = f"{msg_str}，{exist_filenum}个文件已存在"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=msg_title, content=msg_str)
        # 发送消息
        for client in self._active_clients:
            if "transfer_finished" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url='history'
                )

    def send_transfer_tv_message(self, message_medias: dict, in_from: Enum):
        """
        发送转移电视剧/动漫的消息
        """
        for item_info in message_medias.values():
            if item_info.total_episodes == 1:
                msg_title = f"{item_info.get_title_string()} {item_info.get_season_episode_string()} 已入库"
            else:
                msg_title = f"{item_info.get_title_string()} {item_info.get_season_string()} 共{item_info.total_episodes}集 已入库"
            if item_info.vote_average:
                msg_str = f"{item_info.get_vote_string()}，类型：{item_info.type.value}"
            else:
                msg_str = f"类型：{item_info.type.value}"
            if item_info.category:
                msg_str = f"{msg_str}，类别：{item_info.category}"
            if item_info.total_episodes == 1:
                msg_str = f"{msg_str}，大小：{StringUtils.str_filesize(item_info.size)}，来自：{in_from.value}"
            else:
                msg_str = f"{msg_str}，总大小：{StringUtils.str_filesize(item_info.size)}，来自：{in_from.value}"
            # 插入消息中心
            self.messagecenter.insert_system_message(title=msg_title, content=msg_str)
            # 发送消息
            for client in self._active_clients:
                if "transfer_finished" in client.get("switchs"):
                    self.__sendmsg(
                        client=client,
                        title=msg_title,
                        text=msg_str,
                        image=item_info.get_message_image(),
                        url='history')

    def send_download_fail_message(self, item, error_msg):
        """
        发送下载失败的消息
        """
        title = "添加下载任务失败：%s %s" % (item.get_title_string(), item.get_season_episode_string())
        text = f"站点：{item.site}\n种子名称：{item.org_string}\n种子链接：{item.enclosure}\n错误信息：{error_msg}"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "download_fail" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    image=item.get_message_image()
                )

    def send_rss_success_message(self, in_from: Enum, media_info):
        """
        发送订阅成功的消息
        """
        if media_info.type == MediaType.MOVIE:
            msg_title = f"{media_info.get_title_string()} 已添加订阅"
        else:
            msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已添加订阅"
        msg_str = f"类型：{media_info.type.value}"
        if media_info.vote_average:
            msg_str = f"{msg_str}，{media_info.get_vote_string()}"
        msg_str = f"{msg_str}，来自：{in_from.value}"
        if media_info.user_name:
            msg_str = f"{msg_str}，用户：{media_info.user_name}"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=msg_title, content=msg_str)
        # 发送消息
        for client in self._active_clients:
            if "rss_added" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url='movie_rss' if media_info.type == MediaType.MOVIE else 'tv_rss'
                )

    def send_rss_finished_message(self, media_info):
        """
        发送订阅完成的消息，只针对电视剧
        """
        if media_info.type == MediaType.MOVIE:
            return
        else:
            if media_info.over_edition:
                msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已完成洗版"
            else:
                msg_title = f"{media_info.get_title_string()} {media_info.get_season_string()} 已完成订阅"
        msg_str = f"类型：{media_info.type.value}"
        if media_info.vote_average:
            msg_str = f"{msg_str}，{media_info.get_vote_string()}"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=msg_title, content=msg_str)
        # 发送消息
        for client in self._active_clients:
            if "rss_finished" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=msg_title,
                    text=msg_str,
                    image=media_info.get_message_image(),
                    url='downloaded'
                )

    def send_site_signin_message(self, msgs: list):
        """
        发送站点签到消息
        """
        if not msgs:
            return
        title = "站点签到"
        text = "\n".join(msgs)
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "site_signin" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text
                )

    def send_site_message(self, title=None, text=None):
        """
        发送站点消息
        """
        if not title:
            return
        if not text:
            text = ""
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "site_message" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text
                )

    def send_transfer_fail_message(self, path, count, text):
        """
        发送转移失败的消息
        """
        if not path or not count:
            return
        title = f"【{count} 个文件入库失败】"
        text = f"源路径：{path}\n原因：{text}"
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "transfer_fail" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="unidentification"
                )

    def send_auto_remove_torrents_message(self, title, text):
        """
        发送自动删种的消息
        """
        if not title or not text:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "auto_remove_torrents" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="torrent_remove"
                )

    def send_brushtask_remove_message(self, title, text):
        """
        发送刷流删种的消息
        """
        if not title or not text:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "brushtask_remove" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask"
                )

    def send_brushtask_added_message(self, title, text):
        """
        发送刷流下种的消息
        """
        if not title or not text:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "brushtask_added" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask"
                )

    def send_mediaserver_message(self, event_info: dict, channel, image_url):
        """
        发送媒体服务器的消息
        :param event_info: 事件信息
        :param channel: 服务器类型:
        :param image_url: 图片
        """
        if not event_info or not channel:
            return
        # 拼装消息内容
        _webhook_actions = {
            "library.new": "新入库",
            "system.webhooktest": "测试",
            "playback.start": "开始播放",
            "playback.stop": "停止播放",
            "user.authenticated": "登录成功",
            "user.authenticationfailed": "登录失败",
            "media.play": "开始播放",
            "media.stop": "停止播放",
            "PlaybackStart": "开始播放",
            "PlaybackStop": "停止播放",
            "item.rate": "标记了"
        }
        _webhook_images = {
            "Emby": "https://emby.media/notificationicon.png",
            "Plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
            "Jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi"
        }

        if not _webhook_actions.get(event_info.get('event')):
            return

        # 消息标题
        if event_info.get('item_type') in ["TV", "SHOW"]:
            message_title = f"{_webhook_actions.get(event_info.get('event'))}剧集 {event_info.get('item_name')}"
        elif event_info.get('item_type') == "MOV":
            message_title = f"{_webhook_actions.get(event_info.get('event'))}电影 {event_info.get('item_name')}"
        elif event_info.get('item_type') == "AUD":
            message_title = f"{_webhook_actions.get(event_info.get('event'))}有声书 {event_info.get('item_name')}"
        else:
            message_title = f"{_webhook_actions.get(event_info.get('event'))}"

        # 消息内容
        message_texts = []
        if event_info.get('user_name'):
            message_texts.append(f"用户：{event_info.get('user_name')}")
        if event_info.get('device_name'):
            message_texts.append(f"设备：{event_info.get('client')} {event_info.get('device_name')}")
        if event_info.get('ip'):
            message_texts.append(f"位置：{event_info.get('ip')} {WebUtils.get_location(event_info.get('ip'))}")
        if event_info.get('percentage'):
            percentage = round(float(event_info.get('percentage')), 2)
            message_texts.append(f"进度：{percentage}%")
        if event_info.get('overview'):
            message_texts.append(f"剧情：{event_info.get('overview')}")
        message_texts.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

        # 消息图片
        if not image_url:
            image_url = _webhook_images.get(channel)

        # 插入消息中心
        message_content = "\n".join(message_texts)
        self.messagecenter.insert_system_message(title=message_title, content=message_content)

        # 跳转链接
        url = event_info.get('play_url') or ""

        # 发送消息
        for client in self._active_clients:
            if "mediaserver_message" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=message_title,
                    text=message_content,
                    image=image_url,
                    url=url
                )

    def send_plugin_message(self, title, text="", image="", url=""):
        """
        发送插件消息
        """
        if not title:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "custom_message" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url=url,
                    image=image
                )

    def send_custom_message(self, clients, title, text="", image=""):
        """
        发送自定义消息
        """
        if not title:
            return
        if not clients:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if str(client.get("id")) in clients:
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    image=image
                )

    def get_message_client_info(self, cid=None):
        """
        获取消息端信息
        """
        if cid:
            return self._client_configs.get(str(cid))
        return self._client_configs

    def get_interactive_client(self, client_type=None):
        """
        查询当前可以交互的渠道
        """
        if client_type:
            return self._active_interactive_clients.get(client_type)
        else:
            return [client for client in self._active_interactive_clients.values()]

    @staticmethod
    def get_search_types():
        """
        查询可交互的渠道
        """
        return [info.get("search_type")
                for info in ModuleConf.MESSAGE_CONF.get('client').values()
                if info.get('search_type')]

    def send_user_statistics_message(self, msgs: list):
        """
        发送数据统计消息
        """
        if not msgs:
            return
        title = "站点数据统计"
        text = "\n".join(msgs)
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "ptrefresh_date_message" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text
                )

    def delete_message_client(self, cid):
        """
        删除消息端
        """
        ret = self.dbhelper.delete_message_client(cid=cid)
        self.init_config()
        return ret

    def check_message_client(self, cid=None, interactive=None, enabled=None, ctype=None):
        """
        设置消息端
        """
        ret = self.dbhelper.check_message_client(
            cid=cid,
            interactive=interactive,
            enabled=enabled,
            ctype=ctype
        )
        self.init_config()
        return ret

    def insert_message_client(self,
                              name,
                              ctype,
                              config,
                              switchs: list,
                              interactive,
                              enabled,
                              note='',
                              templates=None):
        """
        插入消息端
        """
        ret = self.dbhelper.insert_message_client(
            name=name,
            ctype=ctype,
            config=config,
            switchs=switchs,
            interactive=interactive,
            enabled=enabled,
            note=note,
            templates=templates
        )
        self.init_config()
        return ret

    def send_brushtask_pause_message(self, title, text):
        """
        发送刷流暂停种子的消息
        """
        if not title or not text:
            return
        # 插入消息中心
        self.messagecenter.insert_system_message(title=title, content=text)
        # 发送消息
        for client in self._active_clients:
            if "brushtask_pause" in client.get("switchs"):
                self.__sendmsg(
                    client=client,
                    title=title,
                    text=text,
                    url="brushtask"
                )
