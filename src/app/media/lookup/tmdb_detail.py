import log
from app.domain.mediatypes import MediaType
from app.infrastructure.image_proxy import ImageProxy
from app.infrastructure.request_deduper import get_deduper
from app.media.lookup.tmdb_client import TmdbClient, get_genre_ids_from_detail, update_tmdbinfo_cn_title


class TmdbDetail:
    """TMDB 详情查询"""

    def __init__(self, client: TmdbClient):
        self.client = client

    def get_detail(self, tmdbid, mtype: MediaType, language: str | None = None, append_to_response=None):
        if not mtype:
            mtype = MediaType.UNKNOWN
        if language:
            self.client.set_language(language)
        cached = self.client.redis_cache.get_tmdb_info(mtype, tmdbid, language, extra=append_to_response or "")
        if cached:
            log.debug(f"[Meta]从缓存获取TMDB信息: {mtype.value}/{tmdbid}")
            if language:
                self.client.set_language()
            return cached
        deduper = get_deduper()
        cache_key = f"tmdb_info:{mtype.value}:{tmdbid}:{language or 'default'}:{append_to_response or ''}"

        def _fetch():
            if not self.client.tmdb:
                log.error("[Meta]TMDB API Key 未设置！")
                return None
            if mtype == MediaType.MOVIE:
                info = self._get_movie_detail(tmdbid, append_to_response)
                if info:
                    info["media_type"] = MediaType.MOVIE
            else:
                info = self._get_tv_detail(tmdbid, append_to_response)
                if info:
                    info["media_type"] = MediaType.TV
            if info:
                info["genre_ids"] = get_genre_ids_from_detail(info.get("genres"))
                info = update_tmdbinfo_cn_title(info, self.client._default_language)
            self.client.redis_cache.set_tmdb_info(mtype, tmdbid, info, language, extra=append_to_response or "")
            return info

        result = deduper.execute(cache_key, _fetch)
        if language:
            self.client.set_language()
        return result

    def _get_movie_detail(self, tmdbid, append_to_response=None):
        if not self.client.movie:
            return {}
        try:
            log.info(f"[Meta]正在查询TMDB电影：{tmdbid} ...")
            info = self.client.movie.details(tmdbid, append_to_response or "")
            if info:
                log.info(f"[Meta]{tmdbid} 查询结果：{info.get('title')}")
            return info or {}
        except Exception as e:
            log.warn(f"[TmdbDetail]查询电影详情失败: {e}")
            return None

    def _get_tv_detail(self, tmdbid, append_to_response=None):
        if not self.client.tv:
            return {}
        try:
            log.info(f"[Meta]正在查询TMDB电视剧：{tmdbid} ...")
            info = self.client.tv.details(tmdbid, append_to_response or "")
            if info:
                log.info(f"[Meta]{tmdbid} 查询结果：{info.get('name')}")
            return info or {}
        except Exception as e:
            log.warn(f"[TmdbDetail]查询电视剧详情失败: {e}")
            return None

    def get_season_detail(self, tmdbid, season: int):
        cached = self.client.redis_cache.get_season_info(tmdbid, season)
        if cached:
            log.debug(f"[Meta]从缓存获取季详情: {tmdbid}, 季: {season}")
            return cached
        if not self.client.tv:
            return {}
        try:
            log.info(f"[Meta]正在查询TMDB电视剧：{tmdbid}，季：{season} ...")
            info = self.client.tv.season_details(tmdbid, season)
            result = info or {}
            if result:
                self.client.redis_cache.set_season_info(tmdbid, season, result)
            return result
        except Exception as e:
            log.warn(f"[TmdbDetail]查询季详情失败: {e}")
            return {}

    def get_backdrops(self, tmdbinfo, original=True):
        if not tmdbinfo:
            return []
        prefix_url = (
            ImageProxy.get_tmdbimage_url(r"%s", prefix="original") if original else ImageProxy.get_tmdbimage_url(r"%s")
        )
        backdrops = tmdbinfo.get("images", {}).get("backdrops") or []
        result = [prefix_url % b.get("file_path") for b in backdrops]
        result.append(prefix_url % tmdbinfo.get("backdrop_path"))
        return result

    def get_backdrop(self, mtype, tmdbid):
        if not tmdbid:
            return ""
        tmdbinfo = self.get_detail(tmdbid, mtype)
        if not tmdbinfo:
            return ""
        results = self.get_backdrops(tmdbinfo=tmdbinfo, original=False)
        return results[0] if results else ""
