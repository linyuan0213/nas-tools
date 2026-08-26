import difflib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

from lxml import etree

import log
from app.core.exceptions import TMDBError
from app.domain.mediatypes import MediaType
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.infrastructure.http.exceptions import HttpRateLimitError
from app.infrastructure.tmdb import get_rate_limiter
from app.media.lookup.tmdb_client import TmdbClient, compare_tmdb_names
from app.media.lookup.tmdb_detail import TmdbDetail
from app.utils import StringUtils
from app.utils.config_tools import get_proxies

_STOP_TOKENS = {"THE", "AN", "IN", "OF", "AND", "TO", "FOR", "ON", "WITH", "S", "E", "EP"}


def _tokenize(name: str) -> set[str]:
    clean = re.sub(r"[^A-Za-z0-9]+", " ", str(name)).upper()
    return {w for w in clean.split() if len(w) >= 2}


def _score_fuzzy_match(query_name: str, info: dict, alt_names: list[str], season_number=None) -> float:
    query_norm = cast(str, StringUtils.handler_special_chars(str(query_name))).upper()

    name_score = 0.0
    for name in alt_names:
        tn = cast(str, StringUtils.handler_special_chars(str(name))).upper()
        if query_norm == tn:
            name_score = 1.0
            break
        ratio = difflib.SequenceMatcher(None, query_norm, tn).ratio()
        if ratio > name_score:
            name_score = ratio

    keyword_bonus = 0.0
    query_tokens = _tokenize(query_name) - _STOP_TOKENS
    if query_tokens:
        all_text = " ".join(str(n) for n in alt_names)
        alt_tokens = _tokenize(all_text)
        overlap = len(query_tokens & alt_tokens)
        keyword_bonus = min(0.15, overlap * 0.05)

    season_bonus = 0.0
    if season_number and info:
        seasons = info.get("seasons") or []
        if any(s.get("season_number") == int(season_number) and s.get("episode_count", 0) > 0 for s in seasons):
            season_bonus = 0.05
        else:
            season_bonus = -0.05

    ep_count = info.get("number_of_episodes", 0) or 0
    season_count = info.get("number_of_seasons", 0) or 0
    established_bonus = 0.05 if (ep_count >= 24 or season_count >= 2) else 0.0

    return name_score + keyword_bonus + season_bonus + established_bonus


class TmdbSearch:
    """TMDB 搜索封装"""

    def __init__(self, client: TmdbClient):
        self.client = client
        # 最近一次搜索的错误信息（供上层区分"无结果"与"请求失败"）
        self.last_error: str | None = None

    def search_movie(self, name: str, year: Any = None) -> Any:
        if self.client.search is None:
            return None
        try:
            params = {"query": name}
            if year:
                params["year"] = year
            movies: Any = self.client.search.movies(params)
            blacklist = [str(item.TMDB_ID) for item in self.client.get_blacklist()]
            if movies and blacklist:
                movies = [m for m in movies if not (m.get("id") and str(m.get("id")) in blacklist)]
        except TMDBError as err:
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return None
        except HttpRateLimitError:
            raise
        except Exception as err:
            log.error(f"[Meta]搜索电影时异常：{err!s}")
            return None
        if not movies:
            return {}
        # 第一轮：优先匹配 original_title 完全相等
        for movie in movies:
            year_matched = not year or (movie.get("release_date") and movie.get("release_date", "")[:4] == str(year))
            if not year_matched:
                continue
            original = movie.get("original_title")
            if (
                original
                and str(StringUtils.handler_special_chars(str(original))).strip().upper()
                == str(StringUtils.handler_special_chars(str(name))).strip().upper()
            ):
                return movie
        # 第二轮：模糊匹配 title / original_title
        for movie in movies:
            year_matched = not year or (movie.get("release_date") and movie.get("release_date", "")[:4] == str(year))
            if not year_matched:
                continue
            if compare_tmdb_names(name, movie.get("title")) or compare_tmdb_names(name, movie.get("original_title")):
                return movie
        return self._fuzzy_match_movie(name, year, movies)

    def _fuzzy_match_movie(self, name, year, movies):
        candidates = [m for m in movies[:5] if not year or m.get("release_date", "")[:4] == str(year)]
        if not candidates:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
            future_to_movie = {
                executor.submit(lambda m: (m, self._fetch_allnames(MediaType.MOVIE, m.get("id"))), m): m
                for m in candidates
            }
            for future in as_completed(future_to_movie):
                movie = future_to_movie[future]
                try:
                    results[movie.get("id")] = future.result()
                except Exception as err:
                    log.error(f"[Meta]获取电影详情出错: {err}")
        fuzzy_matches = []
        for movie in candidates:
            res = results.get(movie.get("id"))
            if res:
                _, (info, names) = res
                if compare_tmdb_names(name, names):
                    fuzzy_matches.append((info, names))
        if fuzzy_matches:
            if len(fuzzy_matches) == 1:
                return fuzzy_matches[0][0]
            scored = []
            for info, names in fuzzy_matches:
                score = _score_fuzzy_match(name, info, names)
                scored.append((score, info))
            scored.sort(key=lambda x: -x[0])
            log.debug(
                f"[Meta]_fuzzy_match_movie 多匹配评分: "
                f"{len(scored)} 候选, 最佳={scored[0][1].get('title')} score={scored[0][0]:.3f}"
            )
            return scored[0][1]
        return {}

    def search_tv(self, name: str, year: Any = None, season_number: Any = None, episode: Any = None) -> Any:
        if self.client.search is None:
            return None
        try:
            params = {"query": name}
            if year:
                params["first_air_date_year"] = year
            tvs: Any = self.client.search.tv_shows(params)
            blacklist = [str(item.TMDB_ID) for item in self.client.get_blacklist()]
            if tvs and blacklist:
                tvs = [t for t in tvs if not (t.get("id") and str(t.get("id")) in blacklist)]
        except TMDBError as err:
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return None
        except HttpRateLimitError:
            raise
        except Exception as err:
            log.error(f"[Meta]搜索剧集时异常：{err!s}")
            return None
        if not tvs:
            return {}

        def _episode_valid(tv_info):
            """验证作品集数是否足够容纳目标集号（高集号动漫专用）"""
            if not episode or episode <= 50:
                return True
            detail = self._get_detail(tv_info.get("id"), MediaType.TV)
            ep_count = detail.get("number_of_episodes", 0) if detail else 0
            if ep_count < episode:
                log.debug(f"[Meta]{tv_info.get('name')} 集数({ep_count})不足({episode})，跳过")
                return False
            return True

        # 第一轮：收集所有精确匹配项，优先返回 anime（genre_ids 含 16）
        exact_matches = []
        for tv in tvs:
            year_matched = not year or (tv.get("first_air_date") and tv.get("first_air_date", "")[:4] == str(year))
            if not year_matched:
                continue
            original = tv.get("original_name")
            is_exact = (
                original
                and str(StringUtils.handler_special_chars(str(original))).strip().upper()
                == str(StringUtils.handler_special_chars(str(name))).strip().upper()
            )
            is_fuzzy = compare_tmdb_names(name, tv.get("name")) or compare_tmdb_names(name, tv.get("original_name"))
            if is_exact or is_fuzzy:
                if season_number and not self._tv_has_season(tv.get("id"), season_number):
                    continue
                if _episode_valid(tv):
                    exact_matches.append(tv)
        if exact_matches:
            if len(exact_matches) == 1:
                return exact_matches[0]
            scored = []
            for tv in exact_matches:
                names = [n for n in (tv.get("name"), tv.get("original_name")) if n]
                score = _score_fuzzy_match(name, tv, names, season_number)
                scored.append((score, tv))
            scored.sort(key=lambda x: -x[0])
            best = scored[0][1]
            log.debug(
                f"[Meta]search_tv 多匹配评分: {len(scored)} 候选, 最佳={best.get('name')} score={scored[0][0]:.3f}"
            )
            return best
        return self._fuzzy_match_tv(name, year, tvs, season_number, episode)

    def _fuzzy_match_tv(self, name, year, tvs, season_number=None, episode=None):
        candidates = [t for t in tvs[:5] if not year or t.get("first_air_date", "")[:4] == str(year)]
        if not candidates:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
            future_to_tv = {
                executor.submit(lambda t: (t, self._fetch_allnames(MediaType.TV, t.get("id"))), t): t
                for t in candidates
            }
            for future in as_completed(future_to_tv):
                tv = future_to_tv[future]
                try:
                    results[tv.get("id")] = future.result()
                except Exception as err:
                    log.error(f"[Meta]获取剧集详情出错: {err}")
        fuzzy_matches = []
        for tv in candidates:
            res = results.get(tv.get("id"))
            if res:
                _, (info, names) = res
                if compare_tmdb_names(name, names):
                    if season_number and not self._tv_has_season(tv.get("id"), season_number):
                        continue
                    if episode and episode > 50 and info:
                        ep_count = info.get("number_of_episodes", 0)
                        if ep_count < episode:
                            log.debug(f"[Meta]{info.get('name')} 集数({ep_count})不足({episode})，跳过")
                            continue
                    fuzzy_matches.append((info, names))
        if fuzzy_matches:
            if len(fuzzy_matches) == 1:
                return fuzzy_matches[0][0]
            scored = []
            for info, names in fuzzy_matches:
                score = _score_fuzzy_match(name, info, names, season_number)
                scored.append((score, info))
            scored.sort(key=lambda x: -x[0])
            log.debug(
                f"[Meta]_fuzzy_match_tv 多匹配评分: "
                f"{len(scored)} 候选, 最佳={scored[0][1].get('name')} score={scored[0][0]:.3f}"
            )
            return scored[0][1]
        return {}

    @staticmethod
    def _detail_has_season(tv_info, season_number) -> bool:
        """判断详情中是否存在指定季（且有集）"""
        if not tv_info:
            return False
        seasons = tv_info.get("seasons") or []
        return any(s.get("season_number") == int(season_number) and s.get("episode_count", 0) > 0 for s in seasons)

    def _tv_has_season(self, tmdb_id, season_number):
        """检查 TV 是否有指定的季"""
        try:
            return self._detail_has_season(self._get_detail(tmdb_id, MediaType.TV), season_number)
        except Exception:
            return False

    def search_tv_by_season(self, name: str, media_year: Any, season_number: Any, episode: Any = None) -> Any:
        if self.client.search is None:
            return None

        def _season_match(tv_info, season_year):
            if not tv_info:
                return False
            try:
                seasons = tv_info.get("seasons") or []
                return any(
                    s.get("air_date", "")[:4] == str(season_year) and s.get("season_number") == int(season_number)
                    for s in seasons
                )
            except Exception as e:
                log.error(f"[Meta]连接TMDB出错：{e}")
                return False

        def _episode_valid(tv_info):
            if not episode or episode <= 50:
                return True
            ep_count = tv_info.get("number_of_episodes", 0) if tv_info else 0
            if ep_count < episode:
                log.debug(f"[Meta]{tv_info.get('name')} 集数({ep_count})不足({episode})，跳过")
                return False
            return True

        try:
            tvs: Any = self.client.search.tv_shows({"query": name})
            blacklist = [str(item.TMDB_ID) for item in self.client.get_blacklist()]
            if tvs and blacklist:
                tvs = [t for t in tvs if not (t.get("id") and str(t.get("id")) in blacklist)]
        except TMDBError as err:
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return None
        except HttpRateLimitError:
            raise
        except Exception as err:
            log.error(f"[Meta]按季搜索剧集时异常：{err!s}")
            return None
        if not tvs:
            return {}
        for tv in tvs:
            if (
                compare_tmdb_names(name, tv.get("name")) or compare_tmdb_names(name, tv.get("original_name"))
            ) and tv.get("first_air_date", "")[:4] == str(media_year):
                detail = self._get_detail(tv.get("id"), MediaType.TV)
                # 名称+首播年命中但无目标季（如同名真人剧），跳过避免抢占动漫条目
                if season_number and not self._detail_has_season(detail, season_number):
                    continue
                if _episode_valid(detail):
                    return tv
        candidates = tvs[:5]
        if not candidates:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
            future_to_tv = {
                executor.submit(lambda t: (t, self._fetch_allnames(MediaType.TV, t.get("id"))), t): t
                for t in candidates
            }
            for future in as_completed(future_to_tv):
                tv = future_to_tv[future]
                try:
                    results[tv.get("id")] = future.result()
                except Exception as err:
                    log.error(f"[Meta]获取剧集详情出错: {err}")
        for tv in candidates:
            res = results.get(tv.get("id"))
            if res:
                _, (info, names) = res
                if compare_tmdb_names(name, names) and _season_match(info, media_year) and _episode_valid(info):
                    return info
        return {}

    def search_multi(self, name: str) -> Any:
        if self.client.search is None:
            return None
        try:
            multis: Any = self.client.search.multi({"query": name}) or []
        except TMDBError as err:
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return None
        except HttpRateLimitError:
            raise
        except Exception as err:
            log.error(f"[Meta]多媒体搜索时异常：{err!s}")
            return None
        if not multis:
            return {}
        tv_matches = []
        for multi in multis:
            if multi.get("media_type") == "movie":
                if compare_tmdb_names(name, multi.get("title")) or compare_tmdb_names(
                    name, multi.get("original_title")
                ):
                    return multi
            elif multi.get("media_type") == "tv":
                if compare_tmdb_names(name, multi.get("name")) or compare_tmdb_names(name, multi.get("original_name")):
                    tv_matches.append(multi)
        if tv_matches:
            if len(tv_matches) == 1:
                return tv_matches[0]
            scored = []
            for tv in tv_matches:
                names = [n for n in (tv.get("name"), tv.get("original_name")) if n]
                score = _score_fuzzy_match(name, tv, names)
                scored.append((score, tv))
            scored.sort(key=lambda x: -x[0])
            log.debug(f"[Meta]search_multi TV 多匹配评分完成: {len(scored)} 个候选, 最佳={scored[0][1].get('name')}")
            return scored[0][1]
        tv_matches = []
        for multi in multis[:5]:
            if multi.get("media_type") == "movie":
                movie_info, names = self._fetch_allnames(MediaType.MOVIE, multi.get("id"))
                if compare_tmdb_names(name, names):
                    return movie_info
            elif multi.get("media_type") == "tv":
                tv_info, names = self._fetch_allnames(MediaType.TV, multi.get("id"))
                if compare_tmdb_names(name, names):
                    tv_matches.append((tv_info, names))
        if tv_matches:
            if len(tv_matches) == 1:
                return tv_matches[0][0]
            scored = []
            for info, names in tv_matches:
                score = _score_fuzzy_match(name, info, names)
                scored.append((score, info))
            scored.sort(key=lambda x: -x[0])
            log.debug(f"[Meta]search_multi TV 二次评分完成: {len(scored)} 个候选, 最佳={scored[0][1].get('name')}")
            return scored[0][1]
        return {}

    def search_multi_infos(self, name: str) -> list:
        """查询所有匹配的 movie/tv 结果（用于列表展示，不做名称匹配）"""
        self.last_error = None
        if self.client.search is None:
            return []
        if not name:
            return []
        try:
            multis: Any = self.client.search.multi({"query": name}) or []
        except TMDBError as err:
            self.last_error = str(err)
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return []
        except HttpRateLimitError:
            raise
        except Exception as err:
            self.last_error = str(err)
            log.error(f"[Meta]多媒体信息查询时异常：{err!s}")
            return []
        ret_infos = []
        for multi in multis:
            if multi.get("media_type") in ["movie", "tv"]:
                multi["media_type"] = MediaType.MOVIE if multi.get("media_type") == "movie" else MediaType.TV
                ret_infos.append(multi)
        return ret_infos

    def search_movie_infos(self, name: str, year: Any = None) -> list:
        """查询所有匹配的电影结果（用于列表展示）"""
        self.last_error = None
        if self.client.search is None:
            return []
        if not name:
            return []
        try:
            params = {"query": name}
            if year:
                params["year"] = year
            movies: Any = self.client.search.movies(params) or []
        except TMDBError as err:
            self.last_error = str(err)
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return []
        except Exception as err:
            self.last_error = str(err)
            log.error(f"[Meta]电影信息查询时异常：{err!s}")
            return []
        ret_infos = []
        for movie in movies:
            movie["media_type"] = MediaType.MOVIE
            ret_infos.append(movie)
        return ret_infos

    def search_tv_infos(self, name: str, year: Any = None) -> list:
        """查询所有匹配的电视剧结果（用于列表展示）"""
        self.last_error = None
        if self.client.search is None:
            return []
        if not name:
            return []
        try:
            params = {"query": name}
            if year:
                params["first_air_date_year"] = year
            tvs: Any = self.client.search.tv_shows(params) or []
        except TMDBError as err:
            self.last_error = str(err)
            log.error(f"[Meta]连接TMDB出错：{err!s}")
            return []
        except Exception as err:
            self.last_error = str(err)
            log.error(f"[Meta]剧集信息查询时异常：{err!s}")
            return []
        ret_infos = []
        for tv in tvs:
            tv["media_type"] = MediaType.TV
            ret_infos.append(tv)
        return ret_infos

    def search_web(self, name: str, mtype: MediaType) -> Any:
        if not name or StringUtils.is_chinese(name):
            return None
        log.info(f"[Meta]正在从TheDbMovie网站查询：{name}...")
        tmdb_url = f"https://www.themoviedb.org/search?query={name}"
        tmdb_limiter = get_rate_limiter()
        _proxies = get_proxies() or {}
        _proxy_url = _proxies.get("http") or _proxies.get("https") if isinstance(_proxies, dict) else None
        client = HttpClient(
            config=HttpClientConfig(proxy_url=_proxy_url, timeout=5),
            rate_limiter=tmdb_limiter.engine,
        )
        res = client.get(tmdb_url, rate_limit_key="tmdb:web", rate_limit_rate="2.5/s")
        if not res.text:
            return None
        try:
            html = etree.HTML(res.text)
            xpath = "//a[@data-id and @data-media-type='tv']/@href" if mtype == MediaType.TV else "//a[@data-id]/@href"
            tmdb_links = [
                link for link in cast(list, html.xpath(xpath)) if link and (link.startswith(("/tv", "/movie")))
            ]
            if len(tmdb_links) != 1:
                log.info(f"[Meta]{name} TMDB网站返回{'数据过多' if tmdb_links else '无'}结果")
                return None
            media_type = MediaType.TV if tmdb_links[0].startswith("/tv") else MediaType.MOVIE
            tmdbid = tmdb_links[0].split("/")[-1]
            tmdbinfo = self._get_detail(tmdbid, media_type)
            if not tmdbinfo or (mtype != MediaType.UNKNOWN and tmdbinfo.get("media_type") != mtype):
                return None
            if media_type == MediaType.MOVIE:
                if not (
                    compare_tmdb_names(name, tmdbinfo.get("title"))
                    or compare_tmdb_names(name, tmdbinfo.get("original_title"))
                ):
                    log.info(f"[Meta]{name} TMDB网站返回结果名称不匹配，跳过")
                    return None
            else:
                if not (
                    compare_tmdb_names(name, tmdbinfo.get("name"))
                    or compare_tmdb_names(name, tmdbinfo.get("original_name"))
                ):
                    log.info(f"[Meta]{name} TMDB网站返回结果名称不匹配，跳过")
                    return None
            log.info(
                f"[Meta]{name} 从WEB识别到 {'电影' if media_type == MediaType.MOVIE else '电视剧'}："
                f"TMDBID={tmdbinfo.get('id')}, "
                f"名称={tmdbinfo.get('title' if media_type == MediaType.MOVIE else 'name')}, "
                f"日期={tmdbinfo.get('release_date' if media_type == MediaType.MOVIE else 'first_air_date')}"
            )
            return tmdbinfo
        except Exception as err:
            log.error(f"[Meta]TMDB网站查询出错：{err!s}")
            return None

    def _fetch_allnames(self, mtype, tmdb_id):
        if not mtype or not tmdb_id:
            return {}, []
        ret_names = []
        tmdb_info = TmdbDetail(self.client).get_detail(
            tmdb_id, mtype, append_to_response="alternative_titles,translations"
        )
        if not tmdb_info:
            return tmdb_info, []
        if mtype == MediaType.MOVIE:
            for alt in tmdb_info.get("alternative_titles", {}).get("titles", []):
                title = alt.get("title")
                if title and title not in ret_names:
                    ret_names.append(title)
            for tr in tmdb_info.get("translations", {}).get("translations", []):
                title = tr.get("data", {}).get("title")
                if title and title not in ret_names:
                    ret_names.append(title)
        else:
            for alt in tmdb_info.get("alternative_titles", {}).get("results", []):
                name = alt.get("title")
                if name and name not in ret_names:
                    ret_names.append(name)
            for tr in tmdb_info.get("translations", {}).get("translations", []):
                name = tr.get("data", {}).get("name")
                if name and name not in ret_names:
                    ret_names.append(name)
        return tmdb_info, ret_names

    def _get_detail(self, tmdbid, mtype):
        return TmdbDetail(self.client).get_detail(tmdbid, mtype)
