import hashlib
import threading
from typing import cast

import log
from app.core.settings import settings
from app.core.system_config import SystemConfig
from app.db.repositories.config_repo_adapter import MediaServerRepositoryAdapter
from app.db.repositories.media_sync_repo_adapter import MediaSyncRepositoryAdapter
from app.domain.enums import ProgressKey, SystemConfigKey
from app.domain.mediatypes import MediaType
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.infrastructure.progress import ProgressTracker
from app.infrastructure.queue.base import MessageQueue
from app.media import MediaService
from app.mediaserver.registry import get_all_clients
from app.message import Message
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils

lock = threading.Lock()
server_lock = threading.Lock()


class MediaServer:
    """媒体服务器管理器.

    由 lifespan 通过 AppContext 创建并管理生命周期。
    """

    _server_type: str | None = None
    _server = None
    mediadb: MediaSyncRepositoryAdapter | None = None
    progress: ProgressTracker | None = None
    message: Message | None = None
    media: MediaService | None = None
    systemconfig: SystemConfig | None = None
    config_repo: MediaServerRepositoryAdapter | None = None
    _message_queue: MessageQueue

    def __init__(
        self,
        media_service: MediaService,
        message: Message,
        message_queue: MessageQueue,
        media_sync_repo: MediaSyncRepositoryAdapter | None = None,
        progress_helper: ProgressTracker | None = None,
        system_config: SystemConfig | None = None,
        media_server_repo: MediaServerRepositoryAdapter | None = None,
    ):
        self.mediadb = media_sync_repo or MediaSyncRepositoryAdapter()
        self.message = message
        self.progress = progress_helper or ProgressTracker()
        self.media = media_service
        self.systemconfig = system_config or SystemConfig()
        self.config_repo = media_server_repo or MediaServerRepositoryAdapter()
        self._message_queue = message_queue
        self._server_type = None
        self._server = None

    def _refresh(self):
        """重置服务器实例，下次访问 server property 时重新构建"""
        self._server = None
        self._server_type = None

    def refresh(self) -> None:
        """配置热重载：清除服务器类型与实例缓存，下次访问按新配置重建。"""
        with server_lock:
            self._server_type = None
            self._server = None

    def __build_class(self, ctype, conf):
        for cls in get_all_clients():
            try:
                if cls.match(ctype):
                    return cls(conf)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    @property
    def server(self):
        with server_lock:
            if self._server_type is None:
                if self.config_repo is None:
                    return None
                default_server = self.config_repo.get_default_media_server()
                if default_server:
                    self._server_type = cast(str, default_server.NAME)
                else:
                    # 兼容旧配置：从配置文件读取
                    self._server_type = settings.get("media").get("media_server") or "emby"
            if not self._server:
                self._server = self.__get_server(self._server_type)
            return self._server

    def __get_server(self, ctype: str | None, conf=None):
        return self.__build_class(ctype=ctype, conf=conf)

    def get_type(self):
        """
        当前使用的媒体库服务器
        """
        if not self.server:
            return None
        return self.server.get_type()

    def get_activity_log(self, limit):
        """
        获取媒体服务器的活动日志
        :param limit: 条数限制
        """
        if not self.server:
            return []
        return self.server.get_activity_log(limit)

    def get_user_count(self):
        """
        获取媒体服务器的总用户数
        """
        if not self.server:
            return 0
        return self.server.get_user_count()

    def get_medias_count(self):
        """
        获取媒体服务器各类型的媒体库
        :return: MovieCount SeriesCount SongCount
        """
        if not self.server:
            return None
        return self.server.get_medias_count()

    def refresh_root_library(self):
        """
        刷新媒体服务器整个媒体库
        """
        if not self.server:
            return
        return self.server.refresh_root_library()

    def get_episode_image_by_id(self, item_id, season_id, episode_id):
        """
        根据itemid、season_id、episode_id从Emby查询图片地址
        :param item_id: 在Emby中的ID
        :param season_id: 季
        :param episode_id: 集
        :return: 图片对应在TMDB中的URL
        """
        if not self.server:
            return None
        if not item_id or not season_id or not episode_id:
            return None
        return self.server.get_episode_image_by_id(item_id, season_id, episode_id)

    def get_remote_image_by_id(self, item_id, image_type):
        """
        根据ItemId从媒体服务器查询图片地址
        :param item_id: 在Emby中的ID
        :param image_type: 图片的类弄地，poster或者backdrop等
        :return: 图片对应在TMDB中的URL
        """
        if not self.server:
            return None
        if not item_id:
            return None
        return self.server.get_remote_image_by_id(item_id, image_type)

    def get_local_image_by_id(self, item_id):
        """
        根据ItemId从媒体服务器查询图片地址
        :param item_id: 在Emby中的ID
        """
        if not self.server:
            return None
        if not item_id:
            return None
        return self.server.get_local_image_by_id(item_id)

    def get_no_exists_episodes(self, meta_info, season_number, episode_count):
        """
        根据标题、年份、季、总集数，查询媒体服务器中缺少哪几集
        :param meta_info: 已识别的需要查询的媒体信息
        :param season_number: 季号，数字
        :param episode_count: 该季的总集数
        :return: 该季不存在的集号列表
        """
        if not self.server:
            return None
        return self.server.get_no_exists_episodes(meta_info, season_number, episode_count)

    def get_movies(self, title, year=None):
        """
        根据标题和年份，检查电影是否在媒体服务器中存在，存在则返回列表
        :param title: 标题
        :param year: 年份，可以为空，为空时不按年份过滤
        :return: 含title、year属性的字典列表
        """
        if not self.server:
            return None
        return self.server.get_movies(title, year)

    def refresh_library_by_items(self, items):
        """
        按类型、名称、年份来刷新媒体库
        :param items: 已识别的需要刷新媒体库的媒体信息列表
        """
        if not self.server:
            return
        items_str = str(sorted([str(i) for i in items]))
        lock_key = f"mediaserver:refresh:{hashlib.md5(items_str.encode(), usedforsecurity=False).hexdigest()}"
        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=300)
        acquired = lock.acquire()
        if not acquired:
            log.info("[MediaServer]媒体库刷新正在执行，跳过")
            return
        try:
            return self.server.refresh_library_by_items(items)
        finally:
            lock.release()

    def get_libraries(self):
        """
        获取媒体服务器所有媒体库列表
        """
        if not self.server:
            return []
        return self.server.get_libraries()

    def get_items(self, parent):
        """
        获取媒体库中的所有媒体
        :param parent: 上一级的ID
        """
        if not self.server:
            return []
        return self.server.get_items(parent)

    def get_play_url(self, item_id):
        """
        获取媒体库中的所有媒体
        :param item_id: 媒体的id
        """
        if not self.server:
            return None
        return self.server.get_play_url(item_id)

    def get_tv_episodes(self, item_id):
        """
        获取电视剧的所有集数信息
        :param item_id: 电视剧的ID
        """
        if not self.server:
            return []
        return self.server.get_tv_episodes(item_id=item_id)

    def sync_mediaserver(self):
        """
        同步媒体库所有数据到本地数据库
        锁只保护同步状态检查，IO 密集型操作在锁外执行
        """
        if not self.server:
            return
        if not self.mediadb or not self.progress or not self.systemconfig:
            return

        # 分布式锁：多实例部署时只有一个实例执行媒体库同步
        dist_lock = get_lock_manager().create_lock("mediaserver:sync", ttl_seconds=3600)
        acquired = dist_lock.acquire()
        if not acquired:
            log.info("[MediaServer]媒体库同步正在其他实例执行，跳过")
            return

        try:
            with lock:
                log.info("[MediaServer]开始同步媒体库数据...")
                self.progress.start(ProgressKey.MediaSync)
                self.progress.update(ptype=ProgressKey.MediaSync, text="请稍候...")
                # 获取需同步的媒体库
                librarys = self.systemconfig.get(SystemConfigKey.SyncLibrary) or []
                # 清空登记薄
                self.mediadb.empty(server_type=self._server_type)

            # 汇总统计
            medias_count = self.get_medias_count()
            if not medias_count:
                return
            total_media_count = medias_count.get("MovieCount") + medias_count.get("SeriesCount")
            total_count = 0
            movie_count = 0
            tv_count = 0
            for library in self.get_libraries():
                if str(library.get("id")) not in librarys:
                    continue
                # 获取媒体库所有项目
                self.progress.update(
                    ptype=ProgressKey.MediaSync, text="正在获取 {} 数据...".format(library.get("name"))
                )
                for item in self.get_items(library.get("id")):
                    if not item:
                        continue
                    # 更新进度
                    seasoninfo = []
                    total_count += 1
                    item_type = MediaType.from_string(item.get("type") or "")
                    if item_type == MediaType.MOVIE:
                        movie_count += 1
                    elif item_type == MediaType.TV:
                        tv_count += 1
                        # 查询剧集信息
                        seasoninfo = self.get_tv_episodes(item.get("id"))
                    self.progress.update(
                        ptype=ProgressKey.MediaSync,
                        text="正在同步 {}，已完成：{} / {} ...".format(
                            library.get("name"), total_count, total_media_count
                        ),
                        value=round(100 * total_count / total_media_count, 1),
                    )
                    # 插入数据
                    self.mediadb.insert(server_type=self._server_type, iteminfo=item, seasoninfo=seasoninfo)

            # 更新总体同步情况
            self.mediadb.statistics(
                server_type=self._server_type, total_count=total_count, movie_count=movie_count, tv_count=tv_count
            )
            # 结束进度条
            self.progress.update(
                ptype=ProgressKey.MediaSync, value=100, text=f"媒体库数据同步完成，同步数量：{total_count}"
            )
            self.progress.end(ProgressKey.MediaSync)
            log.info(f"[MediaServer]媒体库数据同步完成，同步数量：{total_count}")
        finally:
            dist_lock.release()

    def check_item_exists(self, mtype, title=None, year=None, tmdbid=None, season=None, episode=None):
        """
        检查媒体库是否已存在某项目，非实时同步数据，仅用于展示
        :param mtype: 媒体类型
        :param title: 标题
        :param year: 年份
        :param tmdbid: TMDB ID
        :param season: 季号
        :param episode: 集号
        :return: 媒体服务器中的ITEMID
        """
        if not self.mediadb:
            return None
        media = self.mediadb.query(server_type=self._server_type, title=title, year=year, tmdbid=tmdbid)
        if not media:
            return None

        # 剧集没有季时默认为第1季
        if mtype != MediaType.MOVIE and not season:
            season = 1
        if season:
            # 匹配剧集是否存在
            seasoninfos = JsonUtils.loads(media.JSON or "[]")
            for seasoninfo in seasoninfos:
                if seasoninfo.get("season_num") == int(season) and (
                    not episode or seasoninfo.get("episode_num") == int(episode)
                ):
                    return media.ITEM_ID
            return None
        else:
            return media.ITEM_ID

    def get_mediasync_status(self):
        """
        获取当前媒体库同步状态
        """
        if not self.mediadb:
            return {}
        status = self.mediadb.get_statistics(server_type=self._server_type)
        if not status:
            return {}
        else:
            return {"movie_count": status.MOVIE_COUNT, "tv_count": status.TV_COUNT, "time": status.UPDATE_TIME}

    def get_iteminfo(self, itemid):
        """
        根据ItemId从媒体服务器查询项目详情
        :param itemid: 在Emby中的ID
        :return: 图片对应在TMDB中的URL
        """
        if not self.server:
            return None
        if not itemid:
            return None
        return self.server.get_iteminfo(itemid)

    def get_playing_sessions(self):
        """
        获取正在播放的会话
        """
        if not self.server:
            return None
        return self.server.get_playing_sessions()

    def _process_webhook(self, event_info: dict, channel: str):
        """异步处理 webhook（图片获取 + 消息发送）"""
        if not self.message:
            return
        try:
            if event_info.get("item_type") == "tv":
                image_url = self.get_episode_image_by_id(
                    item_id=event_info.get("item_id"),
                    season_id=event_info.get("season_id"),
                    episode_id=event_info.get("episode_id"),
                )
            elif event_info.get("item_type") in ["movie", "show"]:
                image_url = self.get_remote_image_by_id(item_id=event_info.get("item_id"), image_type="Backdrop")
            elif event_info.get("item_type") == "AUD":
                image_url = self.get_local_image_by_id(item_id=event_info.get("item_id"))
            else:
                image_url = None
            self.message.send_mediaserver_message(event_info=event_info, channel=channel, image_url=image_url)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error("[MediaServer]webhook 异步处理异常")

    def webhook_message_handler(self, message: str, channel: str):
        """
        处理Webhook消息（快速响应，异步处理，多实例部署时通过分布式锁去重）
        """
        if not self.server:
            return
        if channel != self.server.get_type():
            return
        event_info = None
        try:
            event_info = self.server.get_webhook_message(message)
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error("[MediaServer]webhook 消息解析异常")
            return
        if not event_info:
            return

        # 分布式锁去重：同一事件在多实例环境下只处理一次
        event = event_info.get("event") or "unknown"
        item_id = event_info.get("item_id") or ""
        user_id = event_info.get("user_id") or ""
        timestamp = str(event_info.get("timestamp") or "")
        raw_key = f"{event}:{item_id}:{user_id}:{timestamp}"
        lock_key = f"webhook:{channel}:{hashlib.md5(raw_key.encode(), usedforsecurity=False).hexdigest()}"

        lock = get_lock_manager().create_lock(lock_key, ttl_seconds=60)
        acquired = lock.acquire()
        if not acquired:
            log.debug(f"[MediaServer]webhook 事件已处理，跳过: {raw_key}")
            return

        try:
            self._message_queue.submit(self._process_webhook, event_info, channel, name="mediaserver_webhook")
        finally:
            lock.release()

    def get_resume(self, num=12):
        """
        获取继续观看
        """
        if not self.server:
            return []
        return self.server.get_resume(num=num)

    def get_latest(self, num=20):
        if not self.server:
            return []
        return self.server.get_latest(num=num)

    def download_image(self, url: str) -> bytes | None:
        for cls in get_all_clients():
            server = self.__build_class(cls.client_id, None)
            if server:
                content = server.download_image(url)
                if content:
                    return content
        return None
