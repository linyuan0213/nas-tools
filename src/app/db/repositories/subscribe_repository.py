"""
RSS Repository
Handles RSS movies, TV shows, episodes and history related database operations.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import Integer, cast, or_
from sqlalchemy.exc import IntegrityError

from app.db.models import SubscribeHistory, SubscribeMovies, SubscribeTorrents, SubscribeTvEpisodes, SubscribeTvs
from app.db.repositories.base_repository import BaseRepository
from app.domain.entities.rss import SubscribeState
from app.domain.mediatypes import MediaType
from app.utils.json_utils import JsonUtils

if TYPE_CHECKING:
    from app.media.models import MediaInfo


class SubscribeRepository(BaseRepository):
    """
    RSS订阅仓储
    处理RSS电影、电视剧、剧集和历史记录的数据库操作
    """

    def reset_rss_state(self) -> None:
        """
        初始化时批量重置所有 RSS 订阅状态
        将 STATE='S' 的订阅重置为 STATE='D'，由 SubscriptionMonitor 重新启动队列搜索
        """
        with self.session() as db:
            db.query(SubscribeMovies).filter(SubscribeMovies.STATE == SubscribeState.SEARCHING.value).update(
                {"STATE": SubscribeState.PENDING.value}, synchronize_session=False
            )
            db.query(SubscribeTvs).filter(SubscribeTvs.STATE == SubscribeState.SEARCHING.value).update(
                {"STATE": SubscribeState.PENDING.value}, synchronize_session=False
            )

    # ==================== RSS Movies ====================

    def get_rss_movies(self, state: str | None = None, rssid: int | None = None) -> list[SubscribeMovies]:
        """
        查询订阅电影信息
        """
        with self.session() as db:
            if rssid:
                return db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).all()
            if not state:
                return db.query(SubscribeMovies).all()
            return db.query(SubscribeMovies).filter(state == SubscribeMovies.STATE).all()

    def get_rss_movie_id(self, title: str, year: str | None = None, tmdbid: str | None = None) -> int | str | None:
        """
        获取订阅电影ID
        """
        if not title:
            return None
        with self.session() as db:
            if tmdbid:
                ret = db.query(SubscribeMovies.ID).filter(str(tmdbid) == SubscribeMovies.TMDBID).first()
                if ret:
                    return ret[0]
            query = db.query(SubscribeMovies.ID).filter(title == SubscribeMovies.NAME)
            if year:
                query = query.filter(str(year) == SubscribeMovies.YEAR)
            ret = query.first()
            return ret[0] if ret else None

    def get_rss_tv_id(
        self, title: str, year: str | None = None, season: str | None = None, tmdbid: str | None = None
    ) -> int | str | None:
        """
        获取订阅电视剧ID
        """
        if not title:
            return None
        with self.session() as db:
            if tmdbid:
                query = db.query(SubscribeTvs.ID).filter(str(tmdbid) == SubscribeTvs.TMDBID)
                if season:
                    query = query.filter(str(season) == SubscribeTvs.SEASON)
                ret = query.first()
                if ret:
                    return ret[0]
            query = db.query(SubscribeTvs.ID).filter(title == SubscribeTvs.NAME)
            if season:
                query = query.filter(str(season) == SubscribeTvs.SEASON)
            if year:
                query = query.filter(str(year) == SubscribeTvs.YEAR)
            ret = query.first()
            return ret[0] if ret else None

    def get_subscribe_id(self, mtype, title, year, tmdbid) -> int | None:
        """
        查询订阅ID
        """
        if not title:
            return None
        if mtype == MediaType.MOVIE:
            result = self.get_rss_movie_id(title, year, tmdbid)
        else:
            result = self.get_rss_tv_id(title, year, tmdbid)
        return int(result) if isinstance(result, (int, str)) and str(result).isdigit() else None

    def get_rss_movie_sites(self, rssid: int | None) -> str:
        """
        获取订阅电影站点
        """
        if not rssid:
            return ""
        with self.session() as db:
            ret = db.query(SubscribeMovies.DESC).filter(int(rssid) == SubscribeMovies.ID).first()
            if ret:
                return ret[0]
            return ""

    def update_rss_movie_tmdb(
        self, rid: int, tmdbid: str, title: str, year: str, image: str, desc: str, note: str
    ) -> None:
        """
        更新订阅电影的部分信息
        """
        if not tmdbid:
            return
        with self.session() as db:
            db.query(SubscribeMovies).filter(int(rid) == SubscribeMovies.ID).update(
                {
                    "TMDBID": tmdbid,
                    "NAME": title,
                    "YEAR": year,
                    "IMAGE": image,
                    "NOTE": note,
                    "DESC": desc,
                }
            )

    def update_rss_movie_desc(self, rid: int, desc: str) -> None:
        """
        更新订阅电影的DESC
        """
        with self.session() as db:
            db.query(SubscribeMovies).filter(int(rid) == SubscribeMovies.ID).update({"DESC": desc})

    def update_rss_filter_order(self, rtype: str, rssid: int, res_order: str) -> None:
        """
        更新订阅命中的过滤规则优先级
        """
        with self.session() as db:
            if rtype == MediaType.MOVIE:
                db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).update({"FILTER_ORDER": res_order})
            else:
                db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).update({"FILTER_ORDER": res_order})

    def get_rss_overedition_order(self, rtype: str, rssid: int) -> int:
        """
        查询当前订阅的过滤优先级
        """
        with self.session() as db:
            if rtype == MediaType.MOVIE:
                res = db.query(SubscribeMovies.FILTER_ORDER).filter(int(rssid) == SubscribeMovies.ID).first()
            else:
                res = db.query(SubscribeTvs.FILTER_ORDER).filter(int(rssid) == SubscribeTvs.ID).first()
            if res and res[0]:
                return int(res[0])
            return 0

    def is_exists_rss_movie(self, title: str, year: str | None = None) -> bool:
        """
        判断RSS电影是否存在
        """
        if not title:
            return False
        with self.session() as db:
            if year is not None:
                count = (
                    db.query(SubscribeMovies)
                    .filter(title == SubscribeMovies.NAME, str(year) == SubscribeMovies.YEAR)
                    .count()
                )
            else:
                count = db.query(SubscribeMovies).filter(title == SubscribeMovies.NAME).count()
            return count > 0

    def insert_rss_movie(
        self,
        media_info: MediaInfo,
        state: str = SubscribeState.PENDING.value,
        rss_sites: list | None = None,
        search_sites: list | None = None,
        over_edition: int = 0,
        filter_restype: str | None = None,
        filter_pix: str | None = None,
        filter_team: str | None = None,
        filter_rule: int | str | None = None,
        filter_include: str | None = None,
        filter_exclude: str | None = None,
        filter_free: bool | None = None,
        save_path: str | None = None,
        download_setting: int = -1,
        fuzzy_match: int = 0,
        desc: str | None = None,
        note: str | None = None,
        keyword: str | None = None,
    ) -> int:
        """
        新增RSS电影
        """
        if search_sites is None:
            search_sites = []
        if rss_sites is None:
            rss_sites = []
        over_edition = over_edition or 0
        fuzzy_match = fuzzy_match or 0
        download_setting = download_setting or -1
        filter_restype = filter_restype or ""
        filter_pix = filter_pix or ""
        filter_rule = int(filter_rule) if filter_rule else 0
        filter_team = filter_team or ""
        filter_include = filter_include or ""
        filter_exclude = filter_exclude or ""
        save_path = save_path or ""
        note = note or ""
        keyword = keyword or (media_info.title if media_info else "")
        desc = (desc or "")[:200]
        if not media_info:
            return -1
        if not media_info.title:
            return -1

        with self.session() as db:
            if media_info.year is not None:
                count = (
                    db.query(SubscribeMovies)
                    .filter(media_info.title == SubscribeMovies.NAME, str(media_info.year) == SubscribeMovies.YEAR)
                    .count()
                )
            else:
                count = db.query(SubscribeMovies).filter(media_info.title == SubscribeMovies.NAME).count()
            if count > 0:
                return 9

            try:
                movie = SubscribeMovies(
                    NAME=media_info.title,
                    YEAR=media_info.year,
                    TMDBID=media_info.tmdb_id,
                    IMAGE=media_info.get_poster_image(),
                    RSS_SITES=JsonUtils.dumps(rss_sites),
                    SEARCH_SITES=JsonUtils.dumps(search_sites),
                    OVER_EDITION=over_edition,
                    FILTER_ORDER=0,
                    FILTER_RESTYPE=filter_restype,
                    FILTER_PIX=filter_pix,
                    FILTER_RULE=filter_rule,
                    FILTER_TEAM=filter_team,
                    FILTER_INCLUDE=filter_include,
                    FILTER_EXCLUDE=filter_exclude,
                    FILTER_FREE=None if filter_free is None else int(filter_free),
                    SAVE_PATH=save_path,
                    DOWNLOAD_SETTING=download_setting,
                    FUZZY_MATCH=fuzzy_match,
                    STATE=state,
                    DESC=desc,
                    NOTE=note,
                    KEYWORD=keyword,
                    ADD_DATE=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                db.add(movie)
                db.flush()
                return movie.ID
            except IntegrityError:
                return 9

    def update_rss_movie(self, rssid: int, **kwargs: str | int | list | None) -> int:
        """
        更新RSS电影订阅信息（根据rssid）
        """
        if not rssid:
            return -1
        update_fields = {}
        field_map = {
            "name": "NAME",
            "year": "YEAR",
            "tmdbid": "TMDBID",
            "image": "IMAGE",
            "rss_sites": "RSS_SITES",
            "search_sites": "SEARCH_SITES",
            "over_edition": "OVER_EDITION",
            "filter_restype": "FILTER_RESTYPE",
            "filter_pix": "FILTER_PIX",
            "filter_rule": "FILTER_RULE",
            "filter_team": "FILTER_TEAM",
            "filter_include": "FILTER_INCLUDE",
            "filter_exclude": "FILTER_EXCLUDE",
            "filter_free": "FILTER_FREE",
            "save_path": "SAVE_PATH",
            "download_setting": "DOWNLOAD_SETTING",
            "fuzzy_match": "FUZZY_MATCH",
            "state": "STATE",
            "desc": "DESC",
            "note": "NOTE",
            "keyword": "KEYWORD",
        }
        for k, v in kwargs.items():
            col = field_map.get(k)
            if col is None:
                continue
            if v is None:
                # None = 不更新该字段，保留原值
                continue
            if k in ("rss_sites", "search_sites") and isinstance(v, list):
                update_fields[col] = JsonUtils.dumps(v)
            elif k == "filter_free":
                update_fields[col] = None if v is None else (1 if v else 0)
            else:
                update_fields[col] = v
        if not update_fields:
            return 0
        with self.session() as db:
            db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).update(update_fields)
        return 0

    def delete_rss_movie(
        self, title: str | None = None, year: str | None = None, rssid: int | None = None, tmdbid: str | None = None
    ) -> None:
        """
        删除RSS电影
        """
        if not title and not rssid:
            return
        with self.session() as db:
            if rssid:
                movie = db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).first()
                if movie:
                    title_filter = movie.NAME if movie.NAME else ""
                    year_filter = str(movie.YEAR) if movie.YEAR else ""
                    if title_filter:
                        db.query(SubscribeTorrents).filter(
                            SubscribeTorrents.TITLE == title_filter,
                            SubscribeTorrents.YEAR == year_filter,
                        ).delete()
                db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).delete()
            else:
                if tmdbid:
                    db.query(SubscribeMovies).filter(tmdbid == SubscribeMovies.TMDBID).delete()
                db.query(SubscribeMovies).filter(
                    title == SubscribeMovies.NAME, str(year) == SubscribeMovies.YEAR
                ).delete()

    def update_rss_movie_state(
        self,
        title: str | None = None,
        year: str | None = None,
        rssid: int | None = None,
        state: str = SubscribeState.RUNNING.value,
    ) -> None:
        """
        更新电影订阅状态
        """
        if not title and not rssid:
            return
        with self.session() as db:
            if rssid:
                db.query(SubscribeMovies).filter(int(rssid) == SubscribeMovies.ID).update({"STATE": state})
            else:
                db.query(SubscribeMovies).filter(
                    title == SubscribeMovies.NAME, str(year) == SubscribeMovies.YEAR
                ).update({"STATE": state})

    # ==================== RSS TV Shows ====================

    def get_rss_tvs(self, state: str | None = None, rssid: int | None = None) -> list[SubscribeTvs]:
        """
        查询订阅电视剧信息
        """
        with self.session() as db:
            if rssid:
                return db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).all()
            if not state:
                return db.query(SubscribeTvs).all()
            return db.query(SubscribeTvs).filter(state == SubscribeTvs.STATE).all()

    def get_rss_tv_sites(self, rssid: int | None) -> SubscribeTvs | str:
        """
        获取订阅电视剧站点
        """
        if not rssid:
            return ""
        with self.session() as db:
            ret = db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).first()
            if ret:
                return ret
            return ""

    def update_rss_tv_tmdb(
        self, rid: int, tmdbid: str, title: str, year: str, total: int, lack: int, image: str, desc: str, note: str
    ) -> None:
        """
        更新订阅电视剧的TMDB信息
        """
        if not tmdbid:
            return
        with self.session() as db:
            db.query(SubscribeTvs).filter(int(rid) == SubscribeTvs.ID).update(
                {
                    "TMDBID": tmdbid,
                    "NAME": title,
                    "YEAR": year,
                    "TOTAL": total,
                    "LACK": lack,
                    "IMAGE": image,
                    "DESC": desc,
                    "NOTE": note,
                }
            )

    def update_rss_tv_desc(self, rid: int, desc: str) -> None:
        """
        更新订阅电视剧的DESC
        """
        with self.session() as db:
            db.query(SubscribeTvs).filter(int(rid) == SubscribeTvs.ID).update({"DESC": desc})

    def is_exists_rss_tv(self, title: str, year: str | None = None, season: str | None = None) -> bool:
        """
        判断RSS电视剧是否存在
        """
        if not title:
            return False
        with self.session() as db:
            if season:
                count = (
                    db.query(SubscribeTvs)
                    .filter(title == SubscribeTvs.NAME, str(year) == SubscribeTvs.YEAR, season == SubscribeTvs.SEASON)
                    .count()
                )
            else:
                count = (
                    db.query(SubscribeTvs).filter(title == SubscribeTvs.NAME, str(year) == SubscribeTvs.YEAR).count()
                )
            return count > 0

    def insert_rss_tv(
        self,
        media_info: MediaInfo,
        total: int,
        lack: int = 0,
        state: str = SubscribeState.PENDING.value,
        rss_sites: list | None = None,
        search_sites: list | None = None,
        over_edition: int = 0,
        filter_restype: str | None = None,
        filter_pix: str | None = None,
        filter_team: str | None = None,
        filter_rule: int | str | None = None,
        filter_include: str | None = None,
        filter_exclude: str | None = None,
        filter_free: bool | None = None,
        save_path: str | None = None,
        download_setting: int = -1,
        total_ep: int | str | None = None,
        current_ep: int | str | None = None,
        fuzzy_match: int = 0,
        desc: str | None = None,
        note: str | None = None,
        keyword: str | None = None,
        rssid: int | None = None,
    ) -> int:
        """
        新增RSS电视剧（rssid 不为空时跳过 is_exists 检查，用于编辑替换场景）
        """
        if search_sites is None:
            search_sites = []
        if rss_sites is None:
            rss_sites = []
        over_edition = over_edition or 0
        fuzzy_match = fuzzy_match or 0
        download_setting = download_setting or -1
        filter_restype = filter_restype or ""
        filter_pix = filter_pix or ""
        filter_rule = int(filter_rule) if filter_rule else 0
        filter_team = filter_team or ""
        filter_include = filter_include or ""
        filter_exclude = filter_exclude or ""
        save_path = save_path or ""
        note = note or ""
        keyword = keyword or (media_info.title if media_info else "")
        total_ep = int(total_ep) if total_ep else 0
        current_ep = int(current_ep) if current_ep else 0
        desc = (desc or "")[:200]
        if not media_info:
            return -1
        if not media_info.title:
            return -1
        if fuzzy_match and media_info.begin_season is None:
            season_str = ""
        else:
            season_str = media_info.get_season_string()

        with self.session() as db:
            if not rssid:
                if season_str:
                    count = (
                        db.query(SubscribeTvs)
                        .filter(
                            media_info.title == SubscribeTvs.NAME,
                            str(media_info.year) == SubscribeTvs.YEAR,
                            season_str == SubscribeTvs.SEASON,
                        )
                        .count()
                    )
                else:
                    count = (
                        db.query(SubscribeTvs)
                        .filter(media_info.title == SubscribeTvs.NAME, str(media_info.year) == SubscribeTvs.YEAR)
                        .count()
                    )
                if count > 0:
                    return 9

            try:
                tv = SubscribeTvs(
                    NAME=media_info.title,
                    YEAR=media_info.year,
                    SEASON=season_str,
                    TMDBID=media_info.tmdb_id,
                    IMAGE=media_info.get_poster_image(),
                    RSS_SITES=JsonUtils.dumps(rss_sites),
                    SEARCH_SITES=JsonUtils.dumps(search_sites),
                    OVER_EDITION=over_edition,
                    FILTER_ORDER=0,
                    FILTER_RESTYPE=filter_restype,
                    FILTER_PIX=filter_pix,
                    FILTER_RULE=filter_rule,
                    FILTER_TEAM=filter_team,
                    FILTER_INCLUDE=filter_include,
                    FILTER_EXCLUDE=filter_exclude,
                    FILTER_FREE=None if filter_free is None else int(filter_free),
                    SAVE_PATH=save_path,
                    DOWNLOAD_SETTING=download_setting,
                    FUZZY_MATCH=fuzzy_match,
                    TOTAL_EP=total_ep,
                    CURRENT_EP=current_ep,
                    TOTAL=total,
                    LACK=lack,
                    STATE=state,
                    DESC=desc,
                    NOTE=note,
                    KEYWORD=keyword,
                    ADD_DATE=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                db.add(tv)
                db.flush()
                return tv.ID
            except IntegrityError:
                return 9

    def update_rss_tv(self, rssid: int, **kwargs: str | int | list | None) -> int:
        """
        更新RSS电视剧订阅信息（根据rssid）
        """
        if not rssid:
            return -1
        update_fields = {}
        field_map = {
            "name": "NAME",
            "year": "YEAR",
            "season": "SEASON",
            "tmdbid": "TMDBID",
            "image": "IMAGE",
            "rss_sites": "RSS_SITES",
            "search_sites": "SEARCH_SITES",
            "over_edition": "OVER_EDITION",
            "filter_restype": "FILTER_RESTYPE",
            "filter_pix": "FILTER_PIX",
            "filter_rule": "FILTER_RULE",
            "filter_team": "FILTER_TEAM",
            "filter_include": "FILTER_INCLUDE",
            "filter_exclude": "FILTER_EXCLUDE",
            "filter_free": "FILTER_FREE",
            "save_path": "SAVE_PATH",
            "download_setting": "DOWNLOAD_SETTING",
            "fuzzy_match": "FUZZY_MATCH",
            "total_ep": "TOTAL_EP",
            "current_ep": "CURRENT_EP",
            "total": "TOTAL",
            "lack": "LACK",
            "state": "STATE",
            "desc": "DESC",
            "note": "NOTE",
            "keyword": "KEYWORD",
        }
        for k, v in kwargs.items():
            col = field_map.get(k)
            if col is None:
                continue
            if v is None:
                # None = 不更新该字段，保留原值（避免编辑时意外清空站点/集数等配置）
                continue
            if k in ("rss_sites", "search_sites") and isinstance(v, list):
                update_fields[col] = JsonUtils.dumps(v)
            elif k == "filter_free":
                update_fields[col] = None if v is None else (1 if v else 0)
            else:
                update_fields[col] = v
        if not update_fields:
            return 0
        with self.session() as db:
            db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).update(update_fields)
        return 0

    def update_rss_tv_lack(
        self,
        title: str | None = None,
        year: str | None = None,
        season: str | None = None,
        rssid: int | None = None,
        lack_episodes: list | None = None,
    ) -> None:
        """
        更新电视剧缺失的集数
        """
        if not title and not rssid:
            return
        if not lack_episodes:
            lack = 0
            episodes: list[str] = []
            new_current_ep: int | None = None
        else:
            lack = len(lack_episodes)
            episodes = [str(epi) for epi in lack_episodes]
            # current_ep 语义 = 首个待下载集 → 缺失集最小值（转移/刷新后同步推进）
            nums = [int(e) for e in lack_episodes if str(e).isdigit()]
            new_current_ep = min(nums) if nums else None
        with self.session() as db:
            if rssid:
                # 内联 update_rss_tv_episodes，确保与 LACK 更新在同一事务
                if (
                    db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rssid)).count()
                    > 0
                ):
                    db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rssid)).update(
                        {"EPISODES": ",".join(episodes)}
                    )
                else:
                    db.add(SubscribeTvEpisodes(RSSID=rssid, EPISODES=",".join(episodes)))
                update_fields: dict = {"LACK": lack}
                if new_current_ep is not None:
                    update_fields["CURRENT_EP"] = new_current_ep
                db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).update(update_fields)
            else:
                update_fields = {"LACK": lack}
                if new_current_ep is not None:
                    update_fields["CURRENT_EP"] = new_current_ep
                db.query(SubscribeTvs).filter(
                    title == SubscribeTvs.NAME, str(year) == SubscribeTvs.YEAR, season == SubscribeTvs.SEASON
                ).update(update_fields)

    def update_rss_tv_total(self, rssid: int, total_ep: int, lack_episodes: list | None = None) -> None:
        """更新电视剧总集数（TMDB 集数增加时同步），同时可选更新缺失集"""
        if not rssid:
            return
        lack = len(lack_episodes) if lack_episodes else 0
        episodes_str = ",".join(str(e) for e in lack_episodes) if lack_episodes else ""
        with self.session() as db:
            db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).update(
                {"TOTAL_EP": total_ep, "TOTAL": total_ep, "LACK": lack}
            )
            if rssid:
                existing = db.query(SubscribeTvEpisodes).filter(int(rssid) == SubscribeTvEpisodes.RSSID).first()
                if existing:
                    existing.EPISODES = episodes_str
                else:
                    db.add(SubscribeTvEpisodes(RSSID=str(rssid), EPISODES=episodes_str))

    def delete_rss_tv(
        self, title: str | None = None, season: str | None = None, rssid: int | None = None, tmdbid: str | None = None
    ) -> None:
        """
        删除RSS电视剧
        """
        if not title and not rssid:
            return
        with self.session() as db:
            if not rssid:
                # 内联 get_rss_tv_id 查找，确保后续删除在同一事务上下文
                if tmdbid:
                    if season:
                        ret = (
                            db.query(SubscribeTvs.ID)
                            .filter(tmdbid == SubscribeTvs.TMDBID, season == SubscribeTvs.SEASON)
                            .first()
                        )
                    else:
                        ret = db.query(SubscribeTvs.ID).filter(tmdbid == SubscribeTvs.TMDBID).first()
                    if ret:
                        rssid = ret[0]
                if not rssid:
                    if season:
                        items = (
                            db.query(SubscribeTvs)
                            .filter(title == SubscribeTvs.NAME, str(season) == SubscribeTvs.SEASON)
                            .all()
                        )
                    else:
                        items = db.query(SubscribeTvs).filter(title == SubscribeTvs.NAME).all()
                    if items:
                        if tmdbid:
                            for item in items:
                                if not item.TMDBID or str(tmdbid) == item.TMDBID:
                                    rssid = item.ID
                                    break
                        else:
                            rssid = items[0].ID
            if rssid:
                tv = db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).first()
                if tv:
                    title_filter = tv.NAME if tv.NAME else ""
                    year_filter = str(tv.YEAR) if tv.YEAR else ""
                    season_filter = str(tv.SEASON) if tv.SEASON else ""
                    if title_filter:
                        db.query(SubscribeTorrents).filter(
                            SubscribeTorrents.TITLE == title_filter,
                            SubscribeTorrents.YEAR == year_filter,
                            SubscribeTorrents.SEASON == season_filter,
                        ).delete()
                db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rssid)).delete()
                db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).delete()

    def update_rss_tv_state(
        self,
        title: str | None = None,
        year: str | None = None,
        season: str | None = None,
        rssid: int | None = None,
        state: str = SubscribeState.RUNNING.value,
    ) -> None:
        """
        更新电视剧订阅状态
        """
        if not title and not rssid:
            return
        with self.session() as db:
            if rssid:
                db.query(SubscribeTvs).filter(int(rssid) == SubscribeTvs.ID).update({"STATE": state})
            else:
                db.query(SubscribeTvs).filter(
                    title == SubscribeTvs.NAME, str(year) == SubscribeTvs.YEAR, season == SubscribeTvs.SEASON
                ).update({"STATE": state})

    # ==================== RSS TV Episodes ====================

    def is_exists_rss_tv_episodes(self, rid: int | None) -> bool:
        """
        判断RSS电视剧剧集是否存在
        """
        if not rid:
            return False
        with self.session() as db:
            count = db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rid)).count()
            return count > 0

    def update_rss_tv_episodes(self, rid: int | None, episodes: list | None) -> None:
        """
        插入或更新电视剧订阅缺失剧集
        """
        if not rid:
            return
        if not episodes:
            episodes = []
        else:
            episodes = [str(epi) for epi in episodes]
        with self.session() as db:
            if db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rid)).count() > 0:
                db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rid)).update(
                    {"EPISODES": ",".join(episodes)}
                )
            else:
                db.add(SubscribeTvEpisodes(RSSID=rid, EPISODES=",".join(episodes)))

    def get_rss_tv_episodes(self, rid: int | None) -> list[int] | None:
        """
        查询电视剧订阅缺失剧集
        """
        if not rid:
            return []
        with self.session() as db:
            ret = db.query(SubscribeTvEpisodes.EPISODES).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == rid).first()
            if ret:
                return [int(epi) for epi in str(ret[0]).split(",")]
            return None

    def delete_rss_tv_episodes(self, rid: int | None) -> None:
        """
        删除电视剧订阅缺失剧集
        """
        if not rid:
            return
        with self.session() as db:
            db.query(SubscribeTvEpisodes).filter(cast(SubscribeTvEpisodes.RSSID, Integer) == int(rid)).delete()

    def truncate_rss_episodes(self) -> None:
        """
        清空 RSS 剧集记录（仅清理已完成/失效的订阅关联记录，保护活跃订阅进度）
        """
        with self.session() as db:
            active_ids = {
                row[0]
                for row in db.query(SubscribeTvs.ID)
                .filter(
                    SubscribeTvs.STATE.in_(
                        [SubscribeState.RUNNING.value, SubscribeState.PENDING.value, SubscribeState.SEARCHING.value]
                    )
                )
                .all()
            }
            query = db.query(SubscribeTvEpisodes)
            if active_ids:
                query = query.filter(~cast(SubscribeTvEpisodes.RSSID, Integer).in_(active_ids))
            query.delete(synchronize_session=False)

    # ==================== RSS History ====================

    def get_rss_history(self, rtype: str | None = None, rid: int | None = None) -> list[SubscribeHistory]:
        """
        查询RSS历史
        """
        with self.session() as db:
            if rid:
                return db.query(SubscribeHistory).filter(int(rid) == SubscribeHistory.ID).all()
            if rtype:
                return (
                    db.query(SubscribeHistory)
                    .filter(rtype == SubscribeHistory.TYPE)
                    .order_by(SubscribeHistory.FINISH_TIME.desc())
                    .all()
                )
            return db.query(SubscribeHistory).order_by(SubscribeHistory.FINISH_TIME.desc()).all()

    def is_exists_rss_history(self, rssid: int | None) -> bool:
        """
        判断RSS历史是否存在
        """
        if not rssid:
            return False
        with self.session() as db:
            count = db.query(SubscribeHistory).filter(cast(SubscribeHistory.RSSID, Integer) == rssid).count()
            return count > 0

    def check_rss_history(self, type_str: str, name: str, year: str, season: str) -> bool:
        """
        检查RSS历史是否存在
        """
        with self.session() as db:
            count = (
                db.query(SubscribeHistory)
                .filter(
                    type_str == SubscribeHistory.TYPE,
                    name == SubscribeHistory.NAME,
                    year == SubscribeHistory.YEAR,
                    season == SubscribeHistory.SEASON,
                )
                .count()
            )
            return count > 0

    def insert_rss_history(
        self,
        rssid: int,
        rtype: str,
        name: str,
        year: str,
        tmdbid: str,
        image: str,
        desc: str,
        season: str | None = None,
        total: str | None = None,
        start: str | None = None,
        note: str = "",
    ) -> None:
        """
        登记RSS历史
        """
        with self.session() as db:
            if db.query(SubscribeHistory).filter(cast(SubscribeHistory.RSSID, Integer) == rssid).count() > 0:
                return
            db.add(
                SubscribeHistory(
                    TYPE=rtype,
                    RSSID=rssid,
                    NAME=name,
                    YEAR=year,
                    TMDBID=tmdbid,
                    SEASON=season,
                    IMAGE=image,
                    DESC=desc,
                    TOTAL=total,
                    START=start,
                    NOTE=note,
                    FINISH_TIME=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                )
            )

    def upsert_rss_history(
        self,
        rssid: int,
        rtype: str,
        name: str,
        year: str,
        tmdbid: str,
        image: str,
        desc: str,
        season: str | None = None,
        total: str | None = None,
        start: str | None = None,
        note: str = "",
    ) -> None:
        """
        登记或更新RSS历史：按媒体维度去重，同一 TMDB ID + 季的记录只保留一条
        """
        with self.session() as db:
            # 防御：同一 rssid 已完成过则跳过
            if db.query(SubscribeHistory).filter(cast(SubscribeHistory.RSSID, Integer) == rssid).count() > 0:
                return

            query = db.query(SubscribeHistory).filter(
                SubscribeHistory.TYPE == rtype,
            )
            if season:
                query = query.filter(SubscribeHistory.SEASON == season)
            else:
                query = query.filter(
                    or_(
                        SubscribeHistory.SEASON == None,  # noqa: E711
                        SubscribeHistory.SEASON == "",
                    )
                )
            if tmdbid:
                query = query.filter(SubscribeHistory.TMDBID == tmdbid)
            else:
                query = query.filter(
                    SubscribeHistory.NAME == name,
                    SubscribeHistory.YEAR == year,
                )

            existing = query.first()
            finish_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            if existing:
                existing.RSSID = rssid
                existing.IMAGE = image
                existing.DESC = desc
                existing.TOTAL = total
                existing.START = start
                existing.NOTE = note
                existing.FINISH_TIME = finish_time
            else:
                db.add(
                    SubscribeHistory(
                        TYPE=rtype,
                        RSSID=rssid,
                        NAME=name,
                        YEAR=year,
                        TMDBID=tmdbid,
                        SEASON=season,
                        IMAGE=image,
                        DESC=desc,
                        TOTAL=total,
                        START=start,
                        NOTE=note,
                        FINISH_TIME=finish_time,
                    )
                )

    def delete_rss_history(self, rssid: int | None) -> None:
        """
        删除RSS历史
        """
        if not rssid:
            return
        with self.session() as db:
            db.query(SubscribeHistory).filter(int(rssid) == SubscribeHistory.ID).delete()

    # ==================== RSS Torrents ====================

    def get_rss_torrent_by_enclosure(self, enclosure: str) -> SubscribeTorrents | None:
        """根据 enclosure 获取 RSS 种子记录"""
        if not enclosure:
            return None
        with self.session() as db:
            return db.query(SubscribeTorrents).filter(enclosure == SubscribeTorrents.ENCLOSURE).first()

    def get_rss_torrent_by_name(self, torrent_name: str) -> SubscribeTorrents | None:
        """根据 torrent_name 获取 RSS 种子记录"""
        if not torrent_name:
            return None
        with self.session() as db:
            return db.query(SubscribeTorrents).filter(torrent_name == SubscribeTorrents.TORRENT_NAME).first()

    def insert_rss_torrent(
        self, torrent_name: str, enclosure: str, type_: str, title: str, year: str, season: str, episode: str
    ) -> None:
        """插入 RSS 种子记录"""
        if enclosure and enclosure.startswith("magnet:"):
            enclosure = enclosure.split("&")[0]
        elif enclosure and len(enclosure) > 4000:
            enclosure = enclosure[:4000]
        with self.session() as db:
            db.add(
                SubscribeTorrents(
                    TORRENT_NAME=torrent_name,
                    ENCLOSURE=enclosure,
                    TYPE=type_,
                    TITLE=title,
                    YEAR=year,
                    SEASON=season,
                    EPISODE=episode,
                )
            )

    def simple_insert_rss_torrent(self, title: str, enclosure: str) -> None:
        """简式插入 RSS 种子记录"""
        if enclosure and enclosure.startswith("magnet:"):
            enclosure = enclosure.split("&")[0]
        elif enclosure and len(enclosure) > 4000:
            enclosure = enclosure[:4000]
        with self.session() as db:
            db.add(
                SubscribeTorrents(
                    TORRENT_NAME=title,
                    ENCLOSURE=enclosure,
                )
            )

    def simple_delete_rss_torrent(self, title: str, enclosure: str | None = None) -> None:
        """删除 RSS 种子记录"""
        with self.session() as db:
            if enclosure:
                db.query(SubscribeTorrents).filter(
                    title == SubscribeTorrents.TORRENT_NAME,
                    enclosure == SubscribeTorrents.ENCLOSURE,
                ).delete()
            else:
                db.query(SubscribeTorrents).filter(title == SubscribeTorrents.TORRENT_NAME).delete()

    def truncate_rss_torrents(self) -> None:
        """清空 RSS 种子记录"""
        with self.session() as db:
            db.query(SubscribeTorrents).delete()
