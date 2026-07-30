import re
from typing import Any

import cn2an

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.settings import settings
from app.domain.media_utils import check_media_exists
from app.domain.mediatypes import MediaType
from app.infrastructure.image_proxy import ImageProxy
from app.media import MediaService, meta_info
from app.mediaserver import MediaServer
from app.schemas.media import MediaInfoResultDTO, SeasonEpisodesResultDTO
from app.services.subscribe_service import SubscribeService as Subscribe
from app.services.web import mediainfo_dict
from app.services.web.utils import get_mediainfo_from_id, search_media_infos
from app.utils import StringUtils


class MediaInfoService:
    """
    媒体信息查询业务服务
    负责 TMDB/豆瓣 媒体信息查询、订阅信息回退、季列表等
    """

    def __init__(
        self,
        media_service: MediaService,
        subscribe: Subscribe,
        media_server: MediaServer,
        douban,
    ):
        self._media = media_service
        self._subscribe = subscribe
        self._media_server = media_server
        self._douban = douban

    def get_season_episodes(self, tmdbid, title, year, season) -> SeasonEpisodesResultDTO:
        """查询 TMDB 剧集情况并检查媒体服务器存在状态"""
        episodes = self._media.get_tmdb_season_episodes(tmdbid=tmdbid, season=season)
        for episode in episodes:
            episode.update(
                {
                    "state": bool(
                        self._media_server.check_item_exists(
                            mtype=MediaType.TV,
                            title=title,
                            year=year,
                            tmdbid=tmdbid,
                            season=season,
                            episode=episode.get("episode_number"),
                        )
                    )
                }
            )
        return SeasonEpisodesResultDTO(episodes=episodes)

    def get_tvseason_list(self, tmdbid, title) -> list[dict]:
        """获取剧集季列表"""
        if title:
            title_season = meta_info(title=title).begin_season
        else:
            title_season = None
        if not str(tmdbid).isdigit():
            media_info = get_mediainfo_from_id(mtype=MediaType.TV, mediaid=tmdbid)
            if not media_info or not media_info.tmdb_info:
                return []
            season_infos = self._media.get_tmdb_tv_seasons(media_info.tmdb_info)
        else:
            season_infos = self._media.get_tmdb_tv_seasons_byid(tmdbid=tmdbid)
        if title_season:
            return [{"text": f"第{title_season}季", "num": title_season}]
        return [
            {
                "text": "第{}季".format(cn2an.an2cn(season.get("season_number"), mode="low")),
                "num": season.get("season_number"),
            }
            for season in season_infos
        ]

    def get_media_info_detail(self, mediaid, mtype, title, year, page, rssid) -> MediaInfoResultDTO:
        """
        查询媒体信息（优先订阅信息，不足时回退到 TMDB）
        """
        media_type = MediaType.from_string(mtype)
        if media_type == MediaType.UNKNOWN:
            media_type = MediaType.TV

        rssid_ok = False
        seasons: list[dict] = []
        link_url = ""
        vote_average = 0.0
        poster_path = ""
        release_date = ""
        overview = ""

        if rssid:
            rssid = str(rssid)
            if media_type == MediaType.MOVIE:
                rssinfo = self._subscribe.get_subscribe_movies(rid=int(rssid) if rssid else None)
            else:
                rssinfo = self._subscribe.get_subscribe_tvs(rid=int(rssid) if rssid else None)
            if rssinfo:
                overview = rssinfo[rssid].get("overview") or ""
                poster_path = rssinfo[rssid].get("poster") or ""
                title = rssinfo[rssid].get("name") or ""
                vote_average = rssinfo[rssid].get("vote") or 0.0
                year = rssinfo[rssid].get("year") or ""
                release_date = rssinfo[rssid].get("release_date") or ""
                link_url = self._media.get_detail_url(mtype=media_type, tmdbid=rssinfo[rssid].get("tmdbid"))
                if overview and poster_path:
                    rssid_ok = True

        if not rssid_ok:
            if mediaid:
                media = get_mediainfo_from_id(mtype=media_type, mediaid=mediaid)
            else:
                media = self._media.get_media_info(title=f"{title} {year}", mtype=media_type)
            if not media or not media.tmdb_info:
                return MediaInfoResultDTO(
                    type=mtype, type_str=media_type.value, page=page, title=title or "", year=year or ""
                )
            if not mediaid:
                mediaid = media.tmdb_id
            link_url = media.get_detail_url()
            overview = media.overview or ""
            poster_path = media.get_poster_image() or ""
            title = media.title or ""
            vote_average = round(float(media.vote_average or 0), 1)
            year = media.year or ""
            if media_type != MediaType.MOVIE:
                release_date = media.tmdb_info.get("first_air_date") or ""
                seasons = [
                    {
                        "text": "第{}季".format(cn2an.an2cn(season.get("season_number"), mode="low")),
                        "num": season.get("season_number"),
                    }
                    for season in self._media.get_tmdb_tv_seasons(tv_info=media.tmdb_info)
                ]
            else:
                release_date = media.tmdb_info.get("release_date") or ""
            if not rssid:
                rssid = self._subscribe.get_subscribe_id(
                    mtype=media_type, title=title, tmdbid=str(mediaid) if mediaid else None
                )

        if poster_path:
            poster_path = ImageProxy.get_proxy_image_url(
                poster_path, use_proxy=settings.get("app").get("enable_image_proxy", True)
            )

        return MediaInfoResultDTO(
            type=mtype,
            type_str=media_type.value,
            page=page,
            title=title or "",
            vote_average=vote_average,
            poster_path=poster_path,
            release_date=release_date or "",
            year=year or "",
            overview=overview or "",
            link_url=link_url,
            tmdbid=mediaid,
            rssid=rssid,
            seasons=seasons or [],
        )

    def get_media_person(self, tmdbid, mtype_str, keyword) -> Any:
        """查询演员"""
        mtype = MediaType.MOVIE if MediaType.from_string(mtype_str) == MediaType.MOVIE else MediaType.TV
        if tmdbid:
            return self._media.get_tmdb_cats(tmdbid=tmdbid, mtype=mtype)
        else:
            return self._media.search_tmdb_person(name=keyword)

    def get_media_recommendations(self, tmdbid, mtype_str, page) -> Any:
        """查询推荐"""
        mtype = MediaType.MOVIE if MediaType.from_string(mtype_str) == MediaType.MOVIE else MediaType.TV
        if mtype == MediaType.MOVIE:
            return self._media.get_movie_recommendations(tmdbid=tmdbid, page=page)
        else:
            return self._media.get_tv_recommendations(tmdbid=tmdbid, page=page)

    def get_media_similar(self, tmdbid, mtype_str, page) -> Any:
        """查询相似"""
        mtype = MediaType.MOVIE if MediaType.from_string(mtype_str) == MediaType.MOVIE else MediaType.TV
        if mtype == MediaType.MOVIE:
            return self._media.get_movie_similar(tmdbid=tmdbid, page=page)
        else:
            return self._media.get_tv_similar(tmdbid=tmdbid, page=page)

    def get_person_medias(self, personid, mtype_str, page) -> Any:
        """查询演员参演作品"""
        if mtype_str:
            mtype = MediaType.MOVIE if MediaType.from_string(mtype_str) == MediaType.MOVIE else MediaType.TV
        else:
            mtype = None
        return self._media.get_person_medias(personid=personid, mtype=mtype, page=page)

    def name_test(self, name, subtitle) -> dict:
        """名称识别测试"""
        media_info = self._media.get_media_info(title=name, subtitle=subtitle)
        if not media_info:
            return {"name": "无法识别"}
        return mediainfo_dict(media_info)

    def search_media_infos(self, keyword, source, page) -> list[dict]:
        """搜索媒体词条"""
        medias = search_media_infos(keyword=keyword, source=source, page=page)
        results = []
        for media in medias:
            d = media.to_dict()
            for img_key in ["image", "poster", "backdrop"]:
                if d.get(img_key):
                    d[img_key] = ImageProxy.get_proxy_image_url(d[img_key], use_proxy=True)
            results.append(d)
        return results

    def get_movie_calendar(self, tid, rssid) -> dict | None:
        """查询电影上映日期"""
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = self._douban.get_douban_detail(doubanid=doubanid, mtype=MediaType.MOVIE)
            if not douban_info:
                return None
            poster_path = douban_info.get("cover_url") or ""
            title = douban_info.get("title")
            rating = douban_info.get("rating", {}) or {}
            vote_average = rating.get("value") or "无"
            release_date = douban_info.get("pubdate")
            if release_date:
                release_date = re.sub(r"\(.*\)", "", douban_info.get("pubdate")[0])
            if not release_date:
                return None
            return {
                "type": MediaType.MOVIE.value,
                "title": title,
                "start": release_date,
                "id": tid,
                "year": release_date[0:4] if release_date else "",
                "poster": poster_path,
                "vote_average": vote_average,
                "rssid": rssid,
            }
        else:
            if tid:
                tmdb_info = self._media.get_tmdb_info(mtype=MediaType.MOVIE, tmdbid=tid)
            else:
                return None
            if not tmdb_info:
                return None
            poster_path = (
                ImageProxy.get_tmdbimage_url(tmdb_info.get("poster_path")) if tmdb_info.get("poster_path") else ""
            )
            title = tmdb_info.get("title")
            vote_average = tmdb_info.get("vote_average")
            release_date = tmdb_info.get("release_date")
            if not release_date:
                return None
            return {
                "type": MediaType.MOVIE.value,
                "title": title,
                "start": release_date,
                "id": tid,
                "year": release_date[0:4] if release_date else "",
                "poster": poster_path,
                "vote_average": vote_average,
                "rssid": rssid,
            }

    def get_tv_calendar(self, tid, season, name, rssid) -> list | None:
        """查询电视剧上映日期"""
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = self._douban.get_douban_detail(doubanid=doubanid, mtype=MediaType.TV)
            if not douban_info:
                return None
            poster_path = douban_info.get("cover_url") or ""
            title = douban_info.get("title")
            rating = douban_info.get("rating", {}) or {}
            vote_average = rating.get("value") or "无"
            release_date = re.sub(r"\(.*\)", "", douban_info.get("pubdate")[0])
            if not release_date:
                return None
            return [
                {
                    "type": MediaType.TV.value,
                    "title": title,
                    "start": release_date,
                    "id": tid,
                    "year": release_date[0:4] if release_date else "",
                    "poster": poster_path,
                    "vote_average": vote_average,
                    "rssid": rssid,
                }
            ]
        else:
            if tid:
                tmdb_info = self._media.get_tmdb_tv_season_detail(tmdbid=tid, season=season)
            else:
                return None
            if not tmdb_info:
                return None
            air_date = tmdb_info.get("air_date")
            if not tmdb_info.get("poster_path"):
                tv_tmdb_info = self._media.get_tmdb_info(mtype=MediaType.TV, tmdbid=tid)
                if tv_tmdb_info:
                    poster_path = ImageProxy.get_tmdbimage_url(tv_tmdb_info.get("poster_path"))
                else:
                    poster_path = ""
            else:
                poster_path = ImageProxy.get_tmdbimage_url(tmdb_info.get("poster_path"))
            year = air_date[0:4] if air_date else ""
            events = []
            episodes = tmdb_info.get("episodes") or []
            for episode in episodes:
                if season != 1:
                    title = "{} 第{}季第{}集".format(name, season, episode.get("episode_number"))
                else:
                    title = "{} 第{}集".format(name, episode.get("episode_number"))
                events.append(
                    {
                        "type": MediaType.TV.value,
                        "title": title,
                        "start": episode.get("air_date"),
                        "id": tid,
                        "year": year,
                        "poster": poster_path,
                        "vote_average": episode.get("vote_average") or "无",
                        "rssid": rssid,
                    }
                )
            return events

    def get_media_detail(self, tmdbid, mtype_str) -> dict[str, Any] | None:
        """获取媒体详情"""
        mtype = MediaType.MOVIE if MediaType.from_string(mtype_str) == MediaType.MOVIE else MediaType.TV
        media_info = get_mediainfo_from_id(mtype=mtype, mediaid=tmdbid)
        if not media_info or not media_info.tmdb_info:
            return None
        fav, rssid, item_url = check_media_exists(
            media_server=self._media_server,
            subscribe=self._subscribe,
            mtype=mtype,
            title=media_info.title,
            year=media_info.year,
            mediaid=media_info.tmdb_id,
        )
        seasons = self._media.get_tmdb_tv_seasons(media_info.tmdb_info)
        sub_seasons: list[int] = []
        if mtype == MediaType.TV:
            try:
                sub_seasons = self._subscribe.get_subscribe_seasons(
                    tmdbid=media_info.tmdb_id,
                    title=media_info.title,
                    year=media_info.year,
                )
            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as e:
                log.error(f"[media_detail]查询已订阅季失败: {str(e)}")
        if seasons:
            for season in seasons:
                try:
                    exists = self._media_server.check_item_exists(
                        mtype=mtype,
                        title=media_info.title,
                        year=media_info.year,
                        tmdbid=media_info.tmdb_id,
                        season=season.get("season_number"),
                    )
                    season.update({"state": bool(exists)})
                except (ServiceError, RepositoryError, DomainError):
                    raise
                except Exception as e:
                    log.error(f"[media_detail]检查季存在状态失败: {str(e)}")
                    season.update({"state": False})
        poster_image = media_info.get_poster_image()
        if poster_image:
            poster_image = ImageProxy.get_proxy_image_url(
                poster_image, use_proxy=settings.get("app").get("enable_image_proxy", True)
            )
        return {
            "tmdbid": media_info.tmdb_id,
            "douban_id": media_info.douban_id,
            "type": mtype.value,
            "background": self._media.get_tmdb_backdrops(tmdbinfo=media_info.tmdb_info),
            "image": poster_image,
            "vote": media_info.vote_average,
            "year": media_info.year,
            "title": media_info.title,
            "genres": self._media.get_tmdb_genres_names(tmdbinfo=media_info.tmdb_info),
            "overview": media_info.overview,
            "runtime": StringUtils.str_timehours(media_info.runtime),
            "fact": self._media.get_tmdb_factinfo(media_info),
            "crews": self._media.get_tmdb_crews(tmdbinfo=media_info.tmdb_info, nums=6),
            "actors": self._media.get_tmdb_cats(mtype=mtype, tmdbid=media_info.tmdb_id),
            "link": media_info.get_detail_url(),
            "douban_link": media_info.get_douban_detail_url(),
            "fav": fav,
            "item_url": item_url,
            "rssid": rssid,
            "seasons": seasons,
            "sub_seasons": sub_seasons,
        }
