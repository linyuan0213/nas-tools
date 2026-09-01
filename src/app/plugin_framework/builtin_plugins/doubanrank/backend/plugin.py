"""
DoubanRank Plugin v2
监控豆瓣热门榜单，自动添加订阅
"""

import re
from datetime import datetime
from threading import Event

import defusedxml.minidom  # type: ignore[import-untyped]

import log
from app.domain.enums import SearchType
from app.domain.mediatypes import MediaType
from app.infrastructure.http.client import HttpClient
from app.mediaserver.media_server import MediaServer
from app.plugin_framework.context import PluginContext
from app.services.rss_processor import RssHelper
from app.services.subscribe_service import SubscribeService
from app.services.web.utils import get_mediainfo_from_id
from app.utils import DomUtils
from app.utils.json_utils import JsonUtils


class DoubanRankPlugin:
    """豆瓣榜单订阅插件"""

    def __init__(
        self,
        ctx: PluginContext,
        mediaserver: MediaServer,
        subscribe: SubscribeService,
    ):
        self.ctx = ctx
        self._mediaserver = mediaserver
        self._subscribe = subscribe
        self._rsshelper = RssHelper(site_engine=ctx.site_engine)
        self._media = self.ctx.media_service
        self._event = Event()
        self._douban_address = {
            "movie-ustop": "https://rsshub.app/douban/movie/ustop",
            "movie-weekly": "https://rsshub.app/douban/movie/weekly",
            "movie-real-time": "https://rsshub.app/douban/movie/weekly/subject_real_time_hotest",
            "show-domestic": "https://rsshub.app/douban/movie/weekly/show_domestic",
            "movie-hot-gaia": "https://rsshub.app/douban/movie/weekly/movie_hot_gaia",
            "tv-hot": "https://rsshub.app/douban/movie/weekly/tv_hot",
            "movie-top250": "https://rsshub.app/douban/movie/weekly/movie_top250",
        }

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("豆瓣榜单订阅插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("豆瓣榜单订阅插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行刷新"""
        self.ctx.info("手动触发豆瓣榜单刷新")
        self._refresh_rss(manual=True)

    def _start_service(self):
        config = self._get_config()
        enable = config.get("enable", False)
        cron = config.get("cron")

        if not enable:
            return

        if cron:
            self.ctx.info(f"订阅服务启动，周期：{cron}")
            self.ctx.schedule_cron("refresh", self._refresh_rss, cron=str(cron))

    def _stop_service(self):
        self._event.set()
        try:
            self.ctx.remove_schedule("refresh")
            self.ctx.remove_schedule("refresh_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")
        self._event.clear()

    def _load_history(self):
        content = self.ctx.read_data("history.json")
        if content:
            try:
                return JsonUtils.loads(content)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Plugin]忽略异常: {e}")
        return {}

    def _save_history(self, data):
        self.ctx.write_data("history.json", JsonUtils.dumps(data, ensure_ascii=False, indent=2))

    def _update_history(self, media, state):
        if not media:
            return
        data = self._load_history()
        data[str(media.tmdb_id)] = {
            "id": media.tmdb_id,
            "name": media.title,
            "year": media.year,
            "type": media.type.value if hasattr(media.type, "value") else str(media.type),
            "rating": media.vote_average or 0,
            "image": media.get_poster_image() if hasattr(media, "get_poster_image") else "",
            "state": state,
            "add_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_history(data)

    def _refresh_rss(self, manual=False):
        config = self._get_config()
        enable = config.get("enable", False)
        vote = float(config.get("vote") or 0) if config.get("vote") else 0
        rss_addrs = config.get("rss_addrs", [])
        ranks = config.get("ranks", [])

        if not enable and not manual:
            return

        if isinstance(rss_addrs, str):
            rss_addrs = [a for a in rss_addrs.split("\n") if a]

        addr_list = rss_addrs + [self._douban_address.get(rank) for rank in ranks]
        if not addr_list:
            self.ctx.info("未设置RSS地址")
            return

        self.ctx.info(f"共 {len(addr_list)} 个RSS地址需要刷新")
        for addr in addr_list:
            if not addr:
                continue
            try:
                self.ctx.info(f"获取RSS：{addr} ...")
                rss_infos = self._get_rss_info(addr)
                if not rss_infos:
                    self.ctx.error(f"RSS地址：{addr} ，未查询到数据")
                    continue

                self.ctx.info(f"RSS地址：{addr} ，共 {len(rss_infos)} 条数据")
                for rss_info in rss_infos:
                    if self._event.is_set():
                        self.ctx.info("订阅服务停止")
                        return

                    title = rss_info.get("title")
                    douban_id = rss_info.get("doubanid")
                    mtype = rss_info.get("type")
                    unique_flag = f"doubanrank: {title} (DB:{douban_id})"

                    if self._rsshelper.is_rssd_by_simple(torrent_name=unique_flag, enclosure=None):
                        self.ctx.info(f"已处理过：{title}")
                        continue

                    if douban_id:
                        media_info = get_mediainfo_from_id(mtype=mtype, mediaid=f"DB:{douban_id}", wait=True)
                    else:
                        media_info = self._media.get_media_info(title=title, mtype=mtype)

                    if not media_info:
                        self.ctx.warn(f"未查询到媒体信息：{title}")
                        continue

                    if vote and media_info.vote_average and media_info.vote_average < vote:
                        self.ctx.info(f"{media_info.get_title_string()} 评分低于限制，跳过")
                        continue

                    item_id = self._mediaserver.check_item_exists(
                        mtype=media_info.type,
                        title=media_info.title,
                        year=media_info.year,
                        tmdbid=media_info.tmdb_id,
                        season=media_info.get_season_seq(),
                    )
                    if item_id:
                        self.ctx.info(f"媒体服务器已存在：{media_info.get_title_string()}")
                        self._update_history(media=media_info, state="DOWNLOADED")
                        continue

                    if self._subscribe.check_history(
                        type_str="movie" if media_info.type == MediaType.MOVIE else "tv",
                        name=media_info.title or "",
                        year=media_info.year,
                        season=media_info.get_season_string(),
                    ):
                        self.ctx.info(f"{media_info.get_title_string()} 已订阅过")
                        self._update_history(media=media_info, state="RSS")
                        continue

                    self._rsshelper.simple_insert_rss_torrents(title=unique_flag, enclosure=None)
                    code, msg, rss_media = self._subscribe.add_rss_subscribe(
                        mtype=media_info.type,
                        name=media_info.title,
                        year=media_info.year,
                        season=media_info.begin_season,
                        channel="auto",
                        in_from=str(SearchType.PLUGIN.value),
                    )
                    if not rss_media or code != 0:
                        self.ctx.warn(f"{media_info.get_title_string()} 添加订阅失败：{msg}")
                        if code == 9:
                            self._update_history(media=media_info, state="RSS")
                    else:
                        self.ctx.info(f"{media_info.get_title_string()} 添加订阅成功")
                        self._update_history(media=media_info, state="RSS")
            except Exception as e:
                self.ctx.error(str(e))
        self.ctx.info("所有RSS刷新完成")

    @staticmethod
    def _get_rss_info(addr):
        try:
            ret = HttpClient().get(addr)
            if not ret:
                return []

            ret_xml = ret.text
            ret_array = []
            dom_tree = defusedxml.minidom.parseString(ret_xml)
            root_node = dom_tree.documentElement
            if not root_node:
                return ret_array
            items = root_node.getElementsByTagName("item")
            for item in items:
                try:
                    title = DomUtils.tag_value(item, "title", default="")
                    link = DomUtils.tag_value(item, "link", default="")
                    if not title and not link:
                        continue
                    doubanid = re.findall(r"/(\d+)/", str(link or ""))
                    if doubanid:
                        doubanid = doubanid[0]
                    if doubanid and not str(doubanid).isdigit():
                        continue
                    ret_array.append({"title": title, "link": link, "doubanid": doubanid})
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[DoubanRank]解析 RSS 条目失败: {e}")
                    continue
            return ret_array
        except Exception as e:  # noqa: BLE001
            log.debug(f"[DoubanRank]解析 RSS 失败: {e}")
            return []
