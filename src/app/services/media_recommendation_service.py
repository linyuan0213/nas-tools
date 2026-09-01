import log
from app.domain.media_metadata import (
    _CHINESE_GENRES,
    derive_language_from_country,
    normalize_countries,
    normalize_genres,
    normalize_languages,
)
from app.domain.media_utils import check_media_exists
from app.domain.mediatypes import MediaType
from app.infrastructure.image_proxy import ImageProxy
from app.media import Bangumi, DouBan, MediaService
from app.mediaserver import MediaServer
from app.services.subscribe_service import SubscribeService as Subscribe
from app.services.web.utils import search_media_infos


class MediaRecommendationService:
    """
    媒体推荐/发现业务服务
    """

    def __init__(
        self,
        media_service: MediaService,
        douban: DouBan,
        bangumi: Bangumi,
        media_server: MediaServer,
        subscribe: Subscribe,
        media_info_service,
        downloader_core,
    ):
        self._media = media_service
        self._douban = douban
        self._bangumi = bangumi
        self._media_server = media_server
        self._subscribe = subscribe
        self._media_info_service = media_info_service
        self._downloader_core = downloader_core
        self._genre_cache: dict[str, dict[int, str]] = {}

    def _get_genre_map(self, mtype: MediaType) -> dict[int, str]:
        key = mtype.value
        if key not in self._genre_cache:
            try:
                genres = self._media.get_tmdb_genres(mtype) or []
                genre_map: dict[int, str] = {}
                if isinstance(genres, list):
                    for g in genres:
                        if isinstance(g, dict):
                            gid = g.get("id")
                            gname = g.get("name")
                            if gid is not None:
                                genre_map[int(gid)] = str(gname or "")
                self._genre_cache[key] = genre_map
            except Exception as e:
                log.debug(f"[MediaService]获取类型映射失败: {e}")
                self._genre_cache[key] = {}
        return self._genre_cache[key]

    def _genre_ids_to_names(self, genre_ids: list, mtype: MediaType) -> list[str]:
        if not genre_ids:
            return []
        genre_map = self._get_genre_map(mtype)
        names = [name for gid in genre_ids if (name := genre_map.get(int(gid)))]
        return normalize_genres(names)

    def _parse_douban_overview(self, overview: str) -> tuple[list[str], list[str]]:
        if not overview:
            return [], []
        parts = [p.strip() for p in overview.split("/")]
        if len(parts) < 3:
            return [], []
        year_part = parts[0]
        if not year_part.isdigit() or len(year_part) != 4:
            return [], []
        country = parts[1]
        # 豆瓣 card_subtitle 中类型通常以空格分隔放在第 3 段
        genre_part = parts[2]
        genres = [g for g in genre_part.split() if g in _CHINESE_GENRES]
        return normalize_genres(genres), normalize_countries(country)

    def _enrich_recommend_items(self, items: list[dict], mtype: MediaType | None) -> list[dict]:
        for item in items:
            if not item:
                continue
            genre_ids = item.get("genre_ids")
            origin_country = item.get("origin_country")
            original_language = item.get("original_language")
            overview = item.get("overview", "")
            item_id = str(item.get("id") or "")
            is_bangumi = item_id.startswith("BG:") or item_id.startswith("BGM:")

            if is_bangumi:
                item["genres"] = normalize_genres(["动画"])
                item["countries"] = normalize_countries(["JP"])
                item["languages"] = normalize_languages("ja")
            elif genre_ids:
                item_type = mtype or MediaType.from_string(item.get("type") or "movie")
                item["genres"] = self._genre_ids_to_names(genre_ids, item_type)
                item["countries"] = normalize_countries(origin_country)
                item["languages"] = normalize_languages(original_language)
                if not item["languages"] and item["countries"]:
                    derived = derive_language_from_country(item["countries"])
                    if derived:
                        item["languages"] = [derived]
            elif overview:
                genres, countries = self._parse_douban_overview(overview)
                item["genres"] = genres
                item["countries"] = countries
                item["languages"] = []
                if countries:
                    derived = derive_language_from_country(countries)
                    if derived:
                        item["languages"] = [derived]
            else:
                item["genres"] = []
                item["countries"] = []
                item["languages"] = []
        return items

    def get_recommend_items(self, data: dict) -> list[dict]:
        """
        根据 type/subtype 获取推荐列表
        """
        type_ = data.get("type")
        subtype = data.get("subtype")
        current_page = int(data.get("page", 1))
        res_list = []

        if type_ in [MediaType.MOVIE.value, MediaType.TV.value, "ALL"]:
            if subtype == "hm":
                res_list = self._media.get_tmdb_hot_movies(current_page)
            elif subtype == "ht":
                res_list = self._media.get_tmdb_hot_tvs(current_page)
            elif subtype == "nm":
                res_list = self._media.get_tmdb_new_movies(current_page)
            elif subtype == "nt":
                res_list = self._media.get_tmdb_new_tvs(current_page)
            elif subtype == "dbom":
                res_list = self._douban.get_douban_online_movie(current_page)
            elif subtype == "dbhm":
                res_list = self._douban.get_douban_hot_movie(current_page)
            elif subtype == "dbht":
                res_list = self._douban.get_douban_hot_tv(current_page)
            elif subtype == "dbdh":
                res_list = self._douban.get_douban_hot_anime(current_page)
            elif subtype == "dbnm":
                res_list = self._douban.get_douban_new_movie(current_page)
            elif subtype == "dbtop":
                res_list = self._douban.get_douban_top250_movie(current_page)
            elif subtype == "dbzy":
                res_list = self._douban.get_douban_hot_show(current_page)
            elif subtype == "dbct":
                res_list = self._douban.get_douban_chinese_weekly_tv(current_page)
            elif subtype == "dbgt":
                res_list = self._douban.get_douban_weekly_tv_global(current_page)
            elif subtype == "bangumi":
                week = data.get("week")
                res_list = self._bangumi.get_bangumi_calendar(page=current_page, week=week)
            elif subtype == "sim":
                tmdb_id = data.get("tmdbid")

                res_list = (
                    self._media_info_service.get_media_similar(tmdbid=tmdb_id, mtype_str=type_, page=current_page) or []
                )
            elif subtype == "more":
                tmdb_id = data.get("tmdbid")

                res_list = (
                    self._media_info_service.get_media_recommendations(
                        tmdbid=tmdb_id, mtype_str=type_, page=current_page
                    )
                    or []
                )
            elif subtype == "person":
                person_id = data.get("personid")

                res_list = (
                    self._media_info_service.get_person_medias(
                        personid=person_id, mtype_str=None if type_ == "ALL" else type_, page=current_page
                    )
                    or []
                )
        elif type_ == "SEARCH":
            keyword = data.get("keyword")
            source = data.get("source")
            medias = search_media_infos(keyword=keyword, source=source, page=current_page)
            res_list = [media.to_dict() for media in medias]
        elif type_ == "DOWNLOADED":
            items = self._downloader_core.get_download_history(page=current_page)
            res_list = self._convert_downloaded(items)
        elif type_ == "TRENDING":
            res_list = self._media.get_tmdb_trending_all_week(page=current_page)
        elif type_ == "DISCOVER":
            mtype = MediaType.MOVIE if MediaType.from_string(subtype or "") == MediaType.MOVIE else MediaType.TV
            params = data.get("params") or {}
            res_list = self._media.get_tmdb_discover(mtype=mtype, page=current_page, params=params)
        elif type_ == "DOUBANTAG":
            mtype = MediaType.MOVIE if MediaType.from_string(subtype or "") == MediaType.MOVIE else MediaType.TV
            params = data.get("params") or {}
            sort = params.get("sort") or "R"
            tags = params.get("tags") or ""
            res_list = self._douban.get_douban_disover(mtype=mtype, sort=sort, tags=tags, page=current_page)

        res_list = self._enrich_recommend_items(res_list, None)

        for res in res_list:
            fav, rssid, _ = check_media_exists(
                media_server=self._media_server,
                subscribe=self._subscribe,
                mtype=res.get("type"),
                title=res.get("title"),
                year=res.get("year"),
                mediaid=res.get("id"),
            )
            res.update({"fav": fav, "rssid": rssid})

        try:
            for res in res_list:
                if res.get("image"):
                    res["image"] = ImageProxy.get_proxy_image_url(res["image"], use_proxy=True)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[MediaService]忽略异常: {e}")

        return res_list

    @staticmethod
    def _convert_downloaded(items) -> list[dict]:
        if not items:
            return []
        return [
            {
                "id": item.TMDBID,
                "orgid": item.TMDBID,
                "tmdbid": item.TMDBID,
                "title": item.TITLE,
                "type": MediaType.from_string(item.TYPE).value,
                "media_type": MediaType.from_string(item.TYPE).display_name,
                "year": item.YEAR,
                "vote": item.VOTE,
                "image": item.POSTER,
                "overview": item.TORRENT,
                "date": item.DATE,
                "site": item.SITE,
            }
            for item in items
        ]
