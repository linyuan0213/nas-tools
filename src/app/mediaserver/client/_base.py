import re
from abc import ABCMeta, abstractmethod
from typing import Any
from urllib.parse import quote

import log
from app.core.settings import settings
from app.db.repositories.config_repo_adapter import MediaServerRepositoryAdapter
from app.mediaserver.schema import MediaServerConfigSchema
from app.utils.config_tools import get_domain
from app.utils.json_utils import JsonUtils


class _IMediaClient(metaclass=ABCMeta):
    client_id = ""
    client_type = ""
    client_name = ""
    config_schema: MediaServerConfigSchema | None = None

    def get_db_config(self, name, repo=None):
        """从数据库获取配置，兼容旧配置文件"""
        _repo = repo or MediaServerRepositoryAdapter()
        item = _repo.get_media_server_by_name(name)
        if item and str(item.CONFIG):
            try:
                return JsonUtils.loads(str(item.CONFIG))
            except Exception as e:  # noqa: BLE001
                log.debug(f"[MediaServer]忽略异常: {e}")
        return settings.get(name)

    @classmethod
    @abstractmethod
    def match(cls, ctype) -> Any:
        """
        匹配实例
        """

    @abstractmethod
    def get_type(self) -> Any:
        """
        获取媒体服务器类型
        """

    @abstractmethod
    def get_status(self) -> Any:
        """
        检查连通性
        """

    @abstractmethod
    def get_user_count(self) -> Any:
        """
        获得用户数量
        """

    @abstractmethod
    def get_activity_log(self, num) -> Any:
        """
        获取Emby活动记录
        """

    @abstractmethod
    def get_medias_count(self) -> Any:
        """
        获得电影、电视剧、动漫媒体数量
        :return: MovieCount SeriesCount SongCount
        """

    @abstractmethod
    def get_movies(self, title, year) -> Any:
        """
        根据标题和年份，检查电影是否在存在，存在则返回列表
        :param title: 标题
        :param year: 年份，可以为空，为空时不按年份过滤
        :return: 含title、year属性的字典列表
        """

    @abstractmethod
    def get_tv_episodes(self, item_id=None, title=None, year=None, tmdbid=None, season=None) -> Any:
        """
        根据标题、年份、季查询电视剧所有集信息
        :param item_id: 服务器中的ID
        :param title: 标题
        :param year: 年份，可以为空，为空时不按年份过滤
        :param tmdbid: TMDBID
        :param season: 季号，数字
        :return: 所有集的列表
        """

    @abstractmethod
    def get_no_exists_episodes(self, meta_info, season, total_num) -> Any:
        """
        根据标题、年份、季、总集数，查询缺少哪几集
        :param meta_info: 已识别的需要查询的媒体信息
        :param season: 季号，数字
        :param total_num: 该季的总集数
        :return: 该季不存在的集号列表
        """

    @abstractmethod
    def get_remote_image_by_id(self, item_id, image_type) -> Any:
        """
        根据ItemId查询远程图片地址
        :param item_id: 在服务器中的ID
        :param image_type: 图片的类弄地，poster或者backdrop等
        :return: 图片对应在TMDB中的URL
        """

    @abstractmethod
    def get_local_image_by_id(self, item_id) -> Any:
        """
        根据ItemId查询本地图片地址，需要有外网地址
        :param item_id: 在服务器中的ID
        :return: 图片对应在TMDB中的URL
        """

    @abstractmethod
    def refresh_root_library(self) -> Any:
        """
        刷新整个媒体库
        """

    @abstractmethod
    def refresh_library_by_items(self, items) -> Any:
        """
        按类型、名称、年份来刷新媒体库
        :param items: 已识别的需要刷新媒体库的媒体信息列表
        """

    @abstractmethod
    def get_libraries(self) -> Any:
        """
        获取媒体服务器所有媒体库列表
        """

    @abstractmethod
    def get_items(self, parent) -> Any:
        """
        获取媒体库中的所有媒体
        :param parent: 上一级的ID
        """

    @abstractmethod
    def get_play_url(self, item_id) -> Any:
        """
        获取媒体库中的所有媒体
        :param item_id: 媒体的的ID
        """

    @abstractmethod
    def get_playing_sessions(self) -> Any:
        """
        获取正在播放的会话
        """

    @abstractmethod
    def get_webhook_message(self, message) -> Any:
        """
        解析Webhook报文，获取消息内容结构
        """

    @staticmethod
    def get_nt_image_url(url, remote=False):
        """
        获取NT中转内网图片的地址
        优先使用本地文件缓存代理（/img/tmdb/, /img/douban/, /img/bgm/）
        对于其他图片统一使用本地文件缓存代理（/img/library/）
        当新代理不可用时回退到旧的 Redis 缓存代理（/img?url=）
        :param: url: 图片的URL
        :param: remote: 是否需要返回完整的URL
        """
        if not url:
            return ""

        # 检查是否启用了新的图片代理
        try:
            if settings.get("app").get("enable_image_proxy", True):
                # 处理 TMDB 图片
                if "image.tmdb.org" in url:
                    # 提取路径部分
                    match = re.search(r"/t/p/(\w+)(/.+)", url)
                    if match:
                        size = match.group(1)
                        path = match.group(2).lstrip("/")
                        proxy_url = f"/img/tmdb/{size}/{path}"
                        if remote:
                            domain = get_domain()
                            if domain:
                                return f"{domain}{proxy_url}"
                        return proxy_url

                # 处理豆瓣图片
                if "doubanio.com" in url or "douban.com" in url:
                    encoded_path = quote(url, safe="")
                    proxy_url = f"/img/douban/{encoded_path}"
                    if remote:
                        domain = get_domain()
                        if domain:
                            return f"{domain}{proxy_url}"
                    return proxy_url

                # 处理 Bangumi 图片
                if "lain.bgm.tv" in url:
                    encoded_path = quote(url, safe="")
                    proxy_url = f"/img/bgm/{encoded_path}"
                    if remote:
                        domain = get_domain()
                        if domain:
                            return f"{domain}{proxy_url}"
                    return proxy_url

                # 处理媒体库等其他图片，统一走本地文件缓存代理
                encoded_path = quote(url, safe="")
                proxy_url = f"/img/library/{encoded_path}"
                if remote:
                    domain = get_domain()
                    if domain:
                        return f"{domain}{proxy_url}"
                return proxy_url
        except Exception as e:
            log.error(f"[MediaServer]处理图片代理失败: {str(e)}")

        # 默认使用旧的 Redis 缓存代理
        if remote:
            domain = get_domain()
            if domain:
                return f"{domain}/img?url={quote(url)}"
            else:
                return ""
        else:
            return f"img?url={quote(url)}"

    def download_image(self, url: str) -> bytes | None:
        return None
