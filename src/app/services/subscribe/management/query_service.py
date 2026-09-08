"""Subscribe query service - 订阅查询与删除."""

import re
from typing import Any

from app.domain.mediatypes import MediaType
from app.services.subscribe.management.utils import parse_rss_desc
from app.utils.json_utils import JsonUtils


class SubscribeQueryService:
    """订阅查询服务"""

    def __init__(self, movie_repo, tv_repo, tv_episode_repo, history_repo, sites, indexer_service):
        self._movie_repo = movie_repo
        self._tv_repo = tv_repo
        self._tv_episode_repo = tv_episode_repo
        self._history_repo = history_repo
        self._sites = sites
        self._indexer_service = indexer_service

    def get_subscribe_movies(self, rid: int | None = None, state: str | None = None) -> dict:
        """获取电影订阅"""
        ret_dict = {}
        rss_movies = self._movie_repo.get_all(rssid=rid, state=state)
        rss_sites_valid = self._sites.get_site_names(rss=True)
        search_sites_valid = self._indexer_service.get_user_indexer_names()
        for rss_movie in rss_movies:
            desc = rss_movie.DESC
            note = rss_movie.NOTE
            tmdbid = rss_movie.TMDBID
            rss_sites = JsonUtils.loads(rss_movie.RSS_SITES) if rss_movie.RSS_SITES else []
            search_sites = JsonUtils.loads(rss_movie.SEARCH_SITES) if rss_movie.SEARCH_SITES else []
            over_edition = rss_movie.OVER_EDITION == 1
            filter_restype = rss_movie.FILTER_RESTYPE
            filter_pix = rss_movie.FILTER_PIX
            filter_team = rss_movie.FILTER_TEAM
            filter_rule = rss_movie.FILTER_RULE
            filter_include = rss_movie.FILTER_INCLUDE
            filter_exclude = rss_movie.FILTER_EXCLUDE
            filter_free = bool(rss_movie.FILTER_FREE)
            download_setting = rss_movie.DOWNLOAD_SETTING
            save_path = rss_movie.SAVE_PATH
            fuzzy_match = rss_movie.FUZZY_MATCH == 1
            keyword = rss_movie.KEYWORD
            if desc and desc.find("{") != -1:
                desc = parse_rss_desc(desc)
                rss_sites = desc.get("rss_sites")
                search_sites = desc.get("search_sites")
                over_edition = desc.get("over_edition") == "Y"
                filter_restype = desc.get("restype")
                filter_pix = desc.get("pix")
                filter_team = desc.get("team")
                filter_rule = desc.get("rule")
                download_setting = ""
                save_path = ""
                fuzzy_match = not tmdbid
            if note:
                note_info = parse_rss_desc(note)
            else:
                note_info = {}
            rss_sites = [site for site in (rss_sites or []) if site in rss_sites_valid]
            search_sites = [site for site in (search_sites or []) if site in search_sites_valid]
            ret_dict[str(rss_movie.ID)] = {
                "id": rss_movie.ID,
                "name": rss_movie.NAME,
                "year": rss_movie.YEAR,
                "tmdbid": rss_movie.TMDBID,
                "image": rss_movie.IMAGE,
                "overview": rss_movie.DESC,
                "rss_sites": rss_sites,
                "search_sites": search_sites,
                "over_edition": over_edition,
                "filter_restype": filter_restype,
                "filter_pix": filter_pix,
                "filter_team": filter_team,
                "filter_rule": filter_rule,
                "filter_include": filter_include,
                "filter_exclude": filter_exclude,
                "filter_free": filter_free,
                "save_path": save_path,
                "download_setting": download_setting,
                "fuzzy_match": fuzzy_match,
                "state": rss_movie.STATE,
                "poster": note_info.get("poster"),
                "release_date": note_info.get("release_date"),
                "vote": note_info.get("vote"),
                "keyword": keyword,
                "add_date": rss_movie.ADD_DATE,
            }
        return ret_dict

    def get_subscribe_tvs(self, rid: int | None = None, state: str | None = None) -> dict:
        """获取电视剧订阅"""
        ret_dict = {}
        rss_tvs = self._tv_repo.get_all(rssid=rid, state=state)
        rss_sites_valid = self._sites.get_site_names(rss=True)
        search_sites_valid = self._indexer_service.get_user_indexer_names()
        for rss_tv in rss_tvs:
            desc = rss_tv.DESC
            note = rss_tv.NOTE
            tmdbid = rss_tv.TMDBID
            rss_sites = JsonUtils.loads(rss_tv.RSS_SITES) if rss_tv.RSS_SITES else []
            search_sites = JsonUtils.loads(rss_tv.SEARCH_SITES) if rss_tv.SEARCH_SITES else []
            over_edition = rss_tv.OVER_EDITION == 1
            filter_restype = rss_tv.FILTER_RESTYPE
            filter_pix = rss_tv.FILTER_PIX
            filter_team = rss_tv.FILTER_TEAM
            filter_rule = rss_tv.FILTER_RULE
            filter_include = rss_tv.FILTER_INCLUDE
            filter_exclude = rss_tv.FILTER_EXCLUDE
            filter_free = bool(rss_tv.FILTER_FREE)
            download_setting = rss_tv.DOWNLOAD_SETTING
            save_path = rss_tv.SAVE_PATH
            total_ep = rss_tv.TOTAL_EP
            current_ep = rss_tv.CURRENT_EP
            fuzzy_match = rss_tv.FUZZY_MATCH == 1
            keyword = rss_tv.KEYWORD
            if desc and desc.find("{") != -1:
                desc = parse_rss_desc(desc)
                rss_sites = desc.get("rss_sites")
                search_sites = desc.get("search_sites")
                over_edition = desc.get("over_edition") == "Y"
                filter_restype = desc.get("restype")
                filter_pix = desc.get("pix")
                filter_team = desc.get("team")
                filter_rule = desc.get("rule")
                filter_include = desc.get("include")
                filter_exclude = desc.get("exclude")
                save_path = ""
                download_setting = ""
                total_ep = desc.get("total")
                current_ep = desc.get("current")
                fuzzy_match = not tmdbid
            if note:
                note_info = parse_rss_desc(note)
            else:
                note_info = {}
            rss_sites = [site for site in (rss_sites or []) if site in rss_sites_valid]
            search_sites = [site for site in (search_sites or []) if site in search_sites_valid]
            ret_dict[str(rss_tv.ID)] = {
                "id": rss_tv.ID,
                "name": rss_tv.NAME,
                "year": rss_tv.YEAR,
                "season": rss_tv.SEASON,
                "tmdbid": rss_tv.TMDBID,
                "image": rss_tv.IMAGE,
                "overview": rss_tv.DESC,
                "rss_sites": rss_sites,
                "search_sites": search_sites,
                "over_edition": over_edition,
                "filter_restype": filter_restype,
                "filter_pix": filter_pix,
                "filter_team": filter_team,
                "filter_rule": filter_rule,
                "filter_include": filter_include,
                "filter_exclude": filter_exclude,
                "filter_free": filter_free,
                "save_path": save_path,
                "download_setting": download_setting,
                "total": rss_tv.TOTAL,
                "lack": rss_tv.LACK,
                "total_ep": total_ep,
                "current_ep": current_ep,
                "fuzzy_match": fuzzy_match,
                "state": rss_tv.STATE,
                "poster": note_info.get("poster"),
                "release_date": note_info.get("release_date"),
                "vote": note_info.get("vote"),
                "keyword": keyword,
                "add_date": rss_tv.ADD_DATE,
            }
        return ret_dict

    def get_subscribe_tv_episodes(self, rssid: int | None) -> Any:
        """查询数据库中订阅的电视剧缺失集数"""
        return self._tv_episode_repo.get(int(rssid or 0))

    def get_subscribe_seasons(
        self,
        tmdbid: str | None = None,
        title: str | None = None,
        year: str | None = None,
    ) -> list[int]:
        """获取某部剧集已订阅的季号列表

        SEASON 存储格式为 "S01" 或 "S01-S03"（区间），此处解析为季号整数列表。
        优先按 tmdbid 匹配，其次按名称(+年份)匹配。
        """
        seasons: set[int] = set()
        tmdbid_str = str(tmdbid) if tmdbid else ""
        for rss_tv in self._tv_repo.get_all():
            matched = False
            if tmdbid_str and str(rss_tv.tmdb_id) == tmdbid_str:
                matched = True
            elif not tmdbid_str and title and rss_tv.name == title:
                matched = not year or str(rss_tv.year) == str(year)
            if not matched:
                continue
            seasons.update(self._parse_season_numbers(rss_tv.season))
        return sorted(seasons)

    @staticmethod
    def _parse_season_numbers(season_str: str | None) -> list[int]:
        """将 "S01" / "S01-S03" 解析为季号整数列表"""
        if not season_str:
            return []
        nums = [int(n) for n in re.findall(r"S(\d+)", season_str, flags=re.IGNORECASE)]
        if len(nums) == 2 and nums[0] <= nums[1]:
            return list(range(nums[0], nums[1] + 1))
        return nums

    def check_history(self, type_str: str, name: str, year: str | None, season: str | None) -> bool:
        """检查订阅历史是否存在"""
        return self._history_repo.check_exists(type_str=type_str, name=name, year=year or "", season=season or "")

    def delete_subscribe(
        self,
        mtype: MediaType,
        title: str | None = None,
        year: str | None = None,
        season: str | None = None,
        rssid: int | None = None,
        tmdbid: str | None = None,
    ) -> Any:
        """删除订阅"""
        if mtype == MediaType.MOVIE:
            return self._movie_repo.delete(title=title, year=year, rssid=rssid, tmdbid=tmdbid)
        else:
            return self._tv_repo.delete(title=title, season=season, rssid=rssid, tmdbid=tmdbid)

    def get_subscribe_id(
        self,
        mtype: MediaType,
        title: str,
        year: str | None = None,
        season: str | None = None,
        tmdbid: str | None = None,
    ) -> Any:
        """获取订阅ID"""
        if mtype == MediaType.MOVIE:
            return self._movie_repo.get_id(title=title, year=year, tmdbid=tmdbid)
        else:
            return self._tv_repo.get_id(title=title, year=year, season=season, tmdbid=tmdbid)
