from itertools import count
import os
from urllib.parse import quote
from functools import lru_cache
from urllib.parse import quote_plus
from app.mediaserver.client.fnos_api import FnOSClient
import log
from app.mediaserver.client._base import _IMediaClient
from app.utils import ExceptionUtils
from app.utils.types import MediaServerType, MediaType
from config import Config
from plexapi import media
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer


class FnOS(_IMediaClient):
    # 媒体服务器ID
    client_id = "fnos"
    # 媒体服务器类型
    client_type = MediaServerType.FNOS
    # 媒体服务器名称
    client_name = MediaServerType.FNOS.value

    # 私有属性
    _client_config = {}
    _host = None
    _token = None
    _username = None
    _password = None
    _servername = None
    _fnos = None
    _play_host = None
    _libraries = []

    def __init__(self, config=None):
        if config:
            self._client_config = config
        else:
            self._client_config = Config().get_config('fnos')
        self.init_config()

    def init_config(self):
        if self._client_config:
            self._host = self._client_config.get('host')
            self._username = self._client_config.get('username')
            self._password = self._client_config.get('password')
            if self._host:
                if not self._host.startswith('http'):
                    self._host = "http://" + self._host
                if not self._host.endswith('/'):
                    self._host = self._host + "/"
            self._play_host = self._client_config.get('play_host')
            if not self._play_host:
                self._play_host = self._host
            else:
                if not self._play_host.startswith('http'):
                    self._play_host = "http://" + self._play_host
                if not self._play_host.endswith('/'):
                    self._play_host = self._play_host + "/"
            self._username = self._client_config.get('username')
            self._password = self._client_config.get('password')
            if self._username and self._password:
                try:
                    self._fnos = FnOSClient(
                        base_url=self._host,
                        username=self._username,
                        password=self._password,
                        app_name="trimemedia-web",
                        auth_key="16CCEB3D-AB42-077D-36A1-F355324E4237"
                    )
                    # 检查登录是否成功
                    if self._fnos and hasattr(self._fnos, '_get_token'):
                        try:
                            # 尝试获取token来验证登录是否成功
                            token = self._fnos._get_token()
                            if not token:
                                log.error(f"【{self.client_name}】FnOS服务器登录失败：无法获取有效token")
                                self._fnos = None
                            else:
                                log.info(f"【{self.client_name}】FnOS服务器登录成功")
                        except Exception as e:
                            ExceptionUtils.exception_traceback(e)
                            log.error(f"【{self.client_name}】FnOS服务器登录失败：{str(e)}")
                            self._fnos = None
                except Exception as e:
                    ExceptionUtils.exception_traceback(e)
                    self._fnos = None
                    log.error(f"【{self.client_name}】FnOS服务器连接失败：{str(e)}")

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_type(self):
        return self.client_type

    def get_status(self):
        """
        测试连通性
        """
        return True if self._fnos else False

    def get_user_count(self):
        """
        获得用户数量，FnOS只能配置一个用户
        """
        res = self._fnos.request(
                endpoint="v/api/v1/manager/user/list",
                method="get",
                data={}
            )
        if res['code'] == 0:
            return len(res['data'])
        return 0

    def get_activity_log(self, num):
        """
        获取FnOS活动记录，暂时没有
        """
        if not self._fnos:
            return []
        ret_array = []
        return ret_array

    def get_medias_count(self):
        """
        获得电影、电视剧、动漫媒体数量
        :return: MovieCount SeriesCount SongCount EpisodeCount
        """
        if not self._fnos:
            return {}
        sections = self._fnos.fetch_all_pages()
        MovieCount = SeriesCount = SongCount = EpisodeCount = 0
        for sec in sections:
            if sec.get("type") == "Movie":
                MovieCount += 1
            if sec.get("type") == "TV":
                SeriesCount += int(sec.get("local_number_of_seasons", 0))
                EpisodeCount += int(sec.get("local_number_of_episodes", 0))
        return {
            "MovieCount": MovieCount,
            "SeriesCount": SeriesCount,
            "SongCount": SongCount,
            "EpisodeCount": EpisodeCount
        }

    def get_movies(self, title, year=None):
        """
        根据标题和年份，检查电影是否在FnOS存在，存在则返回列表
        :param title: 标题
        :param year: 年份，为空则不过滤
        :return: 含title、year属性的字典列表
        """
        if not self._fnos:
            return None
        ret_movies = []
        if year:
            movies = self._fnos.search(title=title, year=year, libtype="Movie")
        else:
            movies = self._fnos.search(title=title, libtype="Movie")
        for movie in movies:
            ret_movies.append({'title': movie["title"], 'year': movie["air_date"][:4]})
        return ret_movies

    def get_tv_episodes(self,
                        item_id=None,
                        title=None,
                        year=None,
                        tmdbid=None,
                        season=None):
        """
        根据标题、年份、季查询电视剧所有集信息
        :param item_id: FnOS中的ID
        :param title: 标题
        :param year: 年份，可以为空，为空时不按年份过滤
        :param tmdbid: TMDBID
        :param season: 季号，数字
        :return: 所有集的列表
        """
        if not self._fnos:
            return []
        if not item_id:
            items = self._fnos.search(title=title, year=year, libtype="TV")
            if not items:
                return []
            item_id = items[0].get("guid")

        season_list = self._fnos.get_session_list(item_id)
        
        ret_tvs = []
        for season_dict in season_list:
            if season and season_dict.get("season_number") != int(season):
                continue
            season_id = season_dict.get("guid")
            episodes = self._fnos.get_episode_list(season_id)
            for episode in episodes:
                ret_tvs.append({
                    "season_num": episode.get("season_number"),
                    "episode_num": episode.get("episode_number")
                })
        return ret_tvs

    def get_no_exists_episodes(self, meta_info, season, total_num):
        """
        根据标题、年份、季、总集数，查询FnOS中缺少哪几集
        :param meta_info: 已识别的需要查询的媒体信息
        :param season: 季号，数字
        :param total_num: 该季的总集数
        :return: 该季不存在的集号列表
        """
        if not self._fnos:
            return None
        # 没有季默认为和1季
        if not season:
            season = 1
        episodes = self.get_tv_episodes(title=meta_info.title,
                                        year=meta_info.year,
                                        season=season)
        exists_episodes = [episode['episode_num'] for episode in episodes]
        total_episodes = [episode for episode in range(1, total_num + 1)]
        return list(set(total_episodes).difference(set(exists_episodes)))

    def get_episode_image_by_id(self, item_id, season_id, episode_id):
        """
        根据itemid、season_id、episode_id从FnOS查询图片地址
        :param item_id: 在FnOS中具体的一集的ID
        :param season_id: 季,目前没有使用
        :param episode_id: 集,目前没有使用
        :return: 图片对应在TMDB中的URL
        """
        if not self._fnos:
            return None
        try:
            episode = self._fnos.get_episode_info(item_id)
            if episode:
                return f"{self._host}v/api/v1/sys/img{episode.get('posters')}"
            return None
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取剧集封面出错：" + str(e))
            return None

    def get_remote_image_by_id(self, item_id, image_type):
        """
        根据ItemId从FnOS查询图片地址
        :param item_id: 在Emby中的ID
        :param image_type: 图片的类型，Poster或者Backdrop等
        :return: 图片对应在TMDB中的URL
        """
        if not self._fnos:
            return None
        try:
            episode = self._fnos.get_episode_info(item_id)
            if image_type == "Poster":
               return f"{self._host}v/api/v1/sys/img{episode.get('posters')}"
            else:
                return f"{self._host}v/api/v1/sys/img{episode.get('still_path')}"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.error(f"【{self.client_name}】获取封面出错：" + str(e))
        return None

    def get_local_image_by_id(self, item_id, remote=True):
        """
        根据ItemId从媒体服务器查询有声书图片地址
        :param item_id: 在FnOS中的ID
        :param remote: 是否远程使用
        """
        return None

    def refresh_root_library(self):
        """
        通知Plex刷新整个媒体库
        """
        if not self._fnos:
            return False
        status = False
        for item in self._fnos.get_library_list():
            status = self._fnos.refresh_library(item.get("guid"))
            if not status:
                return status
        return status

    def refresh_library_by_items(self, items):
        """
        按路径刷新媒体库，暂不支持，使用全量刷新
        """
        if not self._fnos:
            return False
        self.refresh_root_library()

    def get_libraries(self):
        """
        获取媒体服务器所有媒体库列表
        """
        if not self._fnos:
            return []
        try:
            self._libraries = self._fnos.get_library_list()
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []
        libraries = []
        for library in self._libraries:
            match library.get("category"):
                case "Movie":
                    library_type = MediaType.MOVIE.value
                    image_list_str = self.get_libraries_image(library.get("guid"), library.get("category"))
                case "TV":
                    library_type = MediaType.TV.value
                    image_list_str = self.get_libraries_image(library.get("guid"), library.get("category"))
                case _:
                    continue
            libraries.append({
                "id": library.get("guid"),
                "name": library.get("title"),
                "paths": "",
                "type": library_type,
                "image_list": image_list_str,
                "link": f"{self._play_host or self._host}v/library/{library.get('guid')}"
            })
        return libraries

    @lru_cache(maxsize=10)
    def get_libraries_image(self, library_key, type):
        """
        获取媒体服务器最近添加的媒体的图片列表
        param: library_key
        param: type type的含义: Movie TV
        """
        if not self._fnos:
            return ""
        # 返回结果
        poster_urls = []
        image_list_str = ""
        library_list = self._fnos.get_library_list()
        for library in library_list:
            if type == library.get("category") and library_key == library.get("guid"):
                posters = library.get("posters")
                poster_urls = [f"{self._host}v/api/v1/sys/img{poster}" for poster in posters]
                image_list_str = ", ".join(
                    [self.get_nt_image_url(url) for url in poster_urls])
        return image_list_str

    def get_iteminfo(self, itemid):
        """
        获取单个项目详情
        """
        if not self._fnos:
            return {}
        try:
            item = self._fnos.get_episode_info(itemid)
            return {'ProviderIds': {'Tmdb': "", 'Imdb': item['imdb_id']}}
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return {}

    def get_play_url(self, item_id, libtype):
        """
        拼装媒体播放链接
        :param item_id: 媒体的的ID
        """
        """v/tv/episode/ v/movie/"""
        url = ""
        if libtype == "TV":
            url = f'{self._play_host or self._host}v/tv/episode/{item_id}'
        else:
            url = f'{self._play_host or self._host}v/movie/{item_id}'
        return url

    def get_items(self, parent):
        """
        获取媒体服务器所有媒体库列表
        """
        if not parent:
            yield {}
        if not self._fnos:
            yield {}
        try:
            items = self._fnos.fetch_all_pages(parent_id=parent)
            for item in items:
                if not item:
                    continue
                path = None
                yield {"id": item.get("guid"),
                        "library": item.get("ancestor_guid"),
                        "type": item.get("type"),
                        "title": item.get("title"),
                        "originalTitle": item.get("title"),
                        "year": item.get("air_date", "")[:4],
                        "tmdbid": "",
                        "imdbid": item.get("imdb_id"),
                        "tvdbid": "",
                        "path": path}
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        yield {}

    def get_playing_sessions(self):
        """
        获取正在播放的会话
        """
        if not self._fnos:
            return []
        ret_sessions = []
        # for session in sessions:
        #     bitrate = sum([m.bitrate or 0 for m in session.media])
        #     ret_sessions.append({
        #         "type": session.TAG,
        #         "bitrate": bitrate,
        #         "address": session.player.address
        #     })
        return ret_sessions

    def get_webhook_message(self, message):
        """
        解析Plex报文
        eventItem  字段的含义
        event      事件类型
        item_type  媒体类型 TV,MOV
        item_name  TV:琅琊榜 S1E6 剖心明志 虎口脱险
                   MOV:猪猪侠大冒险(2001)
        overview   剧情描述
        """
        pass

    def get_resume(self, num=12):
        """
        获取继续观看的媒体
        """
        if not self._fnos:
            return []
        items = self._fnos.get_resume_list()
        ret_resume = []
        for item in items:
            item_type = MediaType.MOVIE.value if item.get("type") == "Movie" else MediaType.TV.value
            if item_type == MediaType.MOVIE.value:
                name = item.get("title")
            else:
                if item.get("season_number") == 1:
                    name = "%s 第%s集" % (item.get("tv_title"), item.get("episode_number") + 1)
                else:
                    name = "%s 第%s季第%s集" % (item.get("tv_title"), item.get("season_number"), item.get("episode_number") + 1)
            link = self.get_play_url(item.get("guid"), libtype=("TV" if item.get("type") != "Movie" else "Movie"))
            image_link = f"{self._host}v/api/v1/sys/img{item.get('poster')}"
            image = self.get_nt_image_url(image_link)
            ret_resume.append({
                "id": item.get("guid"),
                "name": name,
                "type": item_type,
                "image": image,
                "link": link,
                "percent": item.get("ts") / item.get("duration") * 100 if item.get("ts") and item.get("duration") else 0
            })
        return ret_resume

    def get_latest(self, num=20):
        """
        获取最近添加媒体
        """
        if not self._fnos:
            return []
        items = self._fnos.fetch_all_pages(end_page=1)
        count = 0
        ret_resume = []
        for item in items:
            if item.get("path"):
                continue
            item_type = MediaType.MOVIE.value if item.get("type") == "Movie" else MediaType.TV.value
            if item_type == MediaType.MOVIE.value:
                name = item.get("title")
            else:
                if item.get("season_number") == 1:
                    name = "%s 共%s集" % (item.get("title"), item.get("local_number_of_episodes"))
                else:
                    name = "%s 第%s季共%s集" % (item.get("title"), item.get("season_number"), item.get("local_number_of_episodes"))
            link = self.get_play_url(item.get("guid"), libtype=("TV" if item.get("type") != "Movie" else "Movie"))
            image_link = f"{self._host}v/api/v1/sys/img{item.get('poster')}"
            image = self.get_nt_image_url(image_link)
            ret_resume.append({
                "id": item.get("guid"),
                "name": name,
                "type": item_type,
                "image": image,
                "link": link
            })
            count += 1
            if count > num:
                break
        return ret_resume
