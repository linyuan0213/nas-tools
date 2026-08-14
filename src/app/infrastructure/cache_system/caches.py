"""
专用缓存类
提供针对特定业务场景的缓存封装
"""

from typing import Any

import log
from app.domain.mediatypes import MediaType

from .adapters import MemoryCacheAdapter, RedisCacheAdapter
from .base import CacheAdapter


class TypedCache:
    """类型化缓存基类"""

    def __init__(self, adapter: CacheAdapter):
        self._adapter = adapter

    def get(self, key: str) -> Any | None:
        return self._adapter.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return self._adapter.set(key, value, ttl)

    def delete(self, key: str) -> bool:
        return self._adapter.delete(key)

    def exists(self, key: str) -> bool:
        return self._adapter.exists(key)

    def clear(self) -> bool:
        return self._adapter.clear()

    def get_stats(self) -> dict[str, Any]:
        return self._adapter.get_stats()


class TMDBCache(TypedCache):
    """TMDB专用缓存"""

    # 不同数据类型的 TTL（秒）
    TTL_TMDB_INFO = 7 * 24 * 3600  # 7 天
    TTL_MEDIA_INFO = 24 * 3600  # 24 小时
    TTL_SEASON_INFO = 12 * 3600  # 12 小时
    TTL_PERSON_INFO = 30 * 24 * 3600  # 30 天
    TTL_TRENDING = 2 * 3600  # 2 小时
    TTL_DEFAULT = 3600  # 1 小时（默认）

    MEDIA_CACHE_VERSION = "2"  # 匹配逻辑变更时递增，自动作废旧缓存
    TMDB_CACHE_VERSION = "2"  # 中文名补全逻辑变更时递增，自动作废旧缓存（旧缓存可能存英文名）

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            # 默认使用Redis适配器
            adapter = RedisCacheAdapter(name="tmdb")
        super().__init__(adapter)

    def _make_key(self, prefix: str, *parts) -> str:
        """构建缓存键"""
        return f"{prefix}:{':'.join(str(p) for p in parts)}"

    def get_tmdb_info(self, mtype: Any, tmdbid: str, language: str | None = None, extra: str = "") -> Any | None:
        """获取TMDB信息缓存"""

        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        key = self._make_key("tmdb", self.TMDB_CACHE_VERSION, mtype.value, tmdbid, language or "default", extra)
        return self.get(key)

    def set_tmdb_info(
        self, mtype: Any, tmdbid: str, info: Any, language: str | None = None, ttl: int | None = None, extra: str = ""
    ) -> bool:
        """设置TMDB信息缓存"""

        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        key = self._make_key("tmdb", self.TMDB_CACHE_VERSION, mtype.value, tmdbid, language or "default", extra)
        ttl = ttl or self.TTL_TMDB_INFO
        log.debug(f"[TMDBCache]缓存信息: {key}, TTL={ttl}秒")
        return self.set(key, info, ttl)

    def get_media_info(self, title: str, year: str | None = None, mtype: Any = None) -> Any | None:
        """获取媒体信息缓存"""

        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        key = self._make_key("media", self.MEDIA_CACHE_VERSION, title, year or "", mtype.value if mtype else "")
        return self.get(key)

    def set_media_info(
        self, title: str, info: Any, year: str | None = None, mtype: Any = None, ttl: int | None = None
    ) -> bool:
        """设置媒体信息缓存"""

        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        key = self._make_key("media", self.MEDIA_CACHE_VERSION, title, year or "", mtype.value if mtype else "")
        ttl = ttl or self.TTL_MEDIA_INFO
        return self.set(key, info, ttl)

    def get_season_info(self, tmdbid: str, season: int) -> Any | None:
        """获取季详情缓存"""
        key = self._make_key("tmdb:season", tmdbid, season)
        return self.get(key)

    def set_season_info(self, tmdbid: str, season: int, info: Any, ttl: int | None = None) -> bool:
        """设置季详情缓存"""
        key = self._make_key("tmdb:season", tmdbid, season)
        ttl = ttl or self.TTL_SEASON_INFO
        return self.set(key, info, ttl)

    def get_person_info(self, person_id: str) -> Any | None:
        """获取演员信息缓存"""
        key = self._make_key("tmdb:person", person_id)
        return self.get(key)

    def set_person_info(self, person_id: str, info: Any, ttl: int | None = None) -> bool:
        """设置演员信息缓存"""
        key = self._make_key("tmdb:person", person_id)
        ttl = ttl or self.TTL_PERSON_INFO
        return self.set(key, info, ttl)

    def get_trending(self, media_type: str, time_window: str, page: int = 1) -> Any | None:
        """获取热门趋势缓存"""
        key = self._make_key("tmdb:trending", media_type, time_window, page)
        return self.get(key)

    def set_trending(self, media_type: str, time_window: str, page: int, info: Any, ttl: int | None = None) -> bool:
        """设置热门趋势缓存"""
        key = self._make_key("tmdb:trending", media_type, time_window, page)
        ttl = ttl or self.TTL_TRENDING
        return self.set(key, info, ttl)

    def clear_tmdb_cache(self, tmdbid: str) -> None:
        """清除指定TMDB ID的所有缓存（兼容旧版无版本号 key 与新版带版本号 key）"""
        for pattern in (f"tmdb:*:*:{tmdbid}:*", f"tmdb:*:{tmdbid}:*"):
            for key in self._adapter.keys(pattern):
                self._adapter.delete(key)
        log.debug(f"[TMDBCache]清除TMDB ID {tmdbid} 的所有缓存")

    def clear_media_cache(self, title: str) -> None:
        """清除指定标题的所有媒体缓存"""
        pattern = f"media:{title}:*"
        keys = self._adapter.keys(pattern)
        for key in keys:
            self._adapter.delete(key)
        log.debug(f"[TMDBCache]清除标题 {title} 的所有媒体缓存")


class MediaInfoCache(TypedCache):
    """媒体信息缓存"""

    # 默认 TTL：24 小时
    DEFAULT_TTL = 24 * 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=1000, name="media_info", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置媒体信息缓存，默认 TTL 24 小时."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class SearchResultCache(TypedCache):
    """搜索结果缓存"""

    # 默认 TTL：1 小时
    DEFAULT_TTL = 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=500, name="search_result", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置搜索结果缓存，默认 TTL 1 小时."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class TokenCache(TypedCache):
    """Token缓存"""

    # 默认 TTL：7 天
    DEFAULT_TTL = 7 * 24 * 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=512, name="token", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置 Token 缓存，默认 TTL 7 天."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class ConfigLoadCache(TypedCache):
    """配置加载缓存"""

    # 默认 TTL：10 分钟
    DEFAULT_TTL = 600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=1, name="config_load", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置配置加载缓存，默认 TTL 10 分钟."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class CategoryLoadCache(TypedCache):
    """分类加载缓存"""

    # 默认 TTL：10 分钟
    DEFAULT_TTL = 600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=2, name="category_load", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置分类加载缓存，默认 TTL 10 分钟."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class OpenAISessionCache(TypedCache):
    """OpenAI会话缓存"""

    # 默认 TTL：30 天
    DEFAULT_TTL = 30 * 24 * 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=200, name="openai_session", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置 OpenAI 会话缓存，默认 TTL 30 天."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class SiteInfoCache(TypedCache):
    """站点信息缓存"""

    # 默认 TTL：6 小时
    DEFAULT_TTL = 6 * 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=100, name="site_info", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置站点信息缓存，默认 TTL 6 小时."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)


class WordsProcessCache(TypedCache):
    """识别词处理缓存"""

    # 默认 TTL：24 小时
    DEFAULT_TTL = 24 * 3600

    def __init__(self, adapter: CacheAdapter | None = None):
        if adapter is None:
            adapter = MemoryCacheAdapter(maxsize=1000, name="words_process", default_ttl=self.DEFAULT_TTL)
        super().__init__(adapter)

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置识别词处理缓存，默认 TTL 24 小时."""
        ttl = ttl or self.DEFAULT_TTL
        return super().set(key, value, ttl)
