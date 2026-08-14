import difflib

from app.core.settings import settings
from app.db.repositories.plugin_repo_adapter import TmdbBlacklistRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import TMDBCache, get_cache_manager
from app.infrastructure.external.tmdbv3api import (
    TV,
    Discover,
    Episode,
    Find,
    Genre,
    Movie,
    Person,
    Search,
    TMDb,
    Trending,
)
from app.utils import StringUtils
from app.utils.chinese_utils import to_simplified
from app.utils.config_tools import get_tmdbapi_url


class TmdbClient:
    """TMDB API 客户端封装"""

    def __init__(self, tmdb_blacklist_repo: TmdbBlacklistRepositoryAdapter | None = None):
        self.tmdb = None
        self.search = None
        self.movie = None
        self.tv = None
        self.episode = None
        self.person = None
        self.find = None
        self.trending = None
        self.discover = None
        self.genre = None
        self._default_language = "zh"
        self._tmdb_blacklist_repo = tmdb_blacklist_repo or TmdbBlacklistRepositoryAdapter()
        self._init_config()

    def reset(self) -> None:
        """重置配置并清除缓存（热重载时由 ConfigReloader 调用）"""
        self._init_config()
        self.redis_cache.clear()

    def _init_config(self):
        app = settings.get("app")
        media = settings.get("media")
        _lang = media.get("tmdb_language", "zh")
        self._default_language = _lang if isinstance(_lang, str) else "zh"
        _api_key = app.get("rmt_tmdbkey")
        if isinstance(_api_key, str) and _api_key:
            self.tmdb = TMDb()
            self.tmdb.domain = get_tmdbapi_url()
            self.tmdb.api_key = _api_key
            self.tmdb.language = self._default_language
            self.search = Search()
            self.movie = Movie()
            self.tv = TV()
            self.episode = Episode()
            self.find = Find()
            self.person = Person()
            self.trending = Trending()
            self.discover = Discover()
            self.genre = Genre()
        self.redis_cache = TMDBCache(get_cache_manager().get("tmdb"))
        self.blacklist = self._tmdb_blacklist_repo
        self._blacklist_cache = get_cache_manager().get_or_create("tmdb_blacklist", "memory", maxsize=1, ttl=300)

    def get_blacklist(self):
        cached = self._blacklist_cache.get("all")
        if cached is not None:
            return cached
        all_items = self.blacklist.get_tmdb_blacklist()
        self._blacklist_cache.set("all", all_items)
        return all_items

    def set_language(self, language: str = ""):
        if not self.tmdb:
            return
        if language:
            self.tmdb.language = language
        else:
            self.tmdb.language = self._default_language


# ---------- 纯工具函数 ----------


def compare_tmdb_names(file_name, tmdb_names):
    if not file_name or not tmdb_names:
        return False
    if not isinstance(tmdb_names, list):
        tmdb_names = [tmdb_names]
    _fn = StringUtils.handler_special_chars(str(file_name))
    file_name = _fn.upper() if isinstance(_fn, str) else str(file_name).upper()
    file_name_simplified = to_simplified(file_name).upper()
    for tmdb_name in tmdb_names:
        _tn = StringUtils.handler_special_chars(str(tmdb_name))
        tmdb_name = _tn.strip().upper() if isinstance(_tn, str) else str(tmdb_name).strip().upper()
        if file_name == tmdb_name or file_name_simplified == tmdb_name:
            return True
        if len(file_name) < 3 or len(tmdb_name) < 3:
            continue
        is_substring = file_name in tmdb_name or tmdb_name in file_name or file_name_simplified in tmdb_name
        ratio = difflib.SequenceMatcher(None, file_name_simplified, tmdb_name).ratio()
        # 子串匹配阈值放宽：动漫罗马音标题常带 -kun/-chan/-san 等后缀，0.95 过严
        threshold = 0.85 if is_substring else 0.75
        if ratio >= threshold:
            return True
    return False


def get_genre_ids_from_detail(genres):
    if not genres:
        return []
    return [genre.get("id") for genre in genres]


def get_tmdb_chinese_title(tmdbinfo):
    if not tmdbinfo:
        return None
    if tmdbinfo.get("media_type") == MediaType.MOVIE:
        alternative_titles = tmdbinfo.get("alternative_titles", {}).get("titles", [])
    else:
        alternative_titles = tmdbinfo.get("alternative_titles", {}).get("results", [])
    zh_cn = None
    zh_tw = None
    for alternative_title in alternative_titles:
        iso_3166_1 = alternative_title.get("iso_3166_1")
        title = alternative_title.get("title")
        if not title or not StringUtils.is_chinese(title):
            continue
        if iso_3166_1 in ("CN", "SG"):
            simplified = to_simplified(title)
            if simplified == title:
                zh_cn = title
                break
        if iso_3166_1 in ("TW", "HK"):
            zh_tw = title
    if not zh_cn and not zh_tw:
        # 中文名常只存在于 translations（zh-CN/zh），alternative_titles 不一定有 CN/TW 条目
        zh_cn, zh_tw = _get_chinese_title_from_translations(tmdbinfo)
    if zh_cn:
        return zh_cn
    if zh_tw:
        return to_simplified(zh_tw)
    return tmdbinfo.get("title") if tmdbinfo.get("media_type") == MediaType.MOVIE else tmdbinfo.get("name")


def _get_chinese_title_from_translations(tmdbinfo):
    """从 translations 提取中文名：优先 zh-CN/zh（简体），回退 zh-TW/zh-HK（繁体）"""
    zh_cn = None
    zh_tw = None
    for tr in (tmdbinfo.get("translations") or {}).get("translations") or []:
        iso = str(tr.get("iso_639_1") or "")
        if not iso.lower().startswith("zh"):
            continue
        data = tr.get("data") or {}
        title = data.get("title") or data.get("name")
        if not title or not StringUtils.is_chinese(title):
            continue
        if iso.lower() in ("zh-cn", "zh-sg", "zh"):
            simplified = to_simplified(title)
            if simplified == title:
                zh_cn = title
                break
        if iso.lower() in ("zh-tw", "zh-hk", "zh-mo"):
            zh_tw = title
    return zh_cn, zh_tw


def update_tmdbinfo_cn_title(tmdb_info, default_language):
    org_title = tmdb_info.get("title") if tmdb_info.get("media_type") == MediaType.MOVIE else tmdb_info.get("name")
    # 中文语言配置（zh/zh-CN/zh-Hans...）下补全中文名；非中文配置保持原样
    if not StringUtils.is_chinese(org_title) and str(default_language or "").lower().startswith("zh"):
        cn_title = get_tmdb_chinese_title(tmdbinfo=tmdb_info)
        if cn_title and cn_title != org_title:
            if tmdb_info.get("media_type") == MediaType.MOVIE:
                tmdb_info["title"] = cn_title
            else:
                tmdb_info["name"] = cn_title
    return tmdb_info
