import log
import pickle
from typing import Optional, Dict, Any
from app.utils.redis_store import RedisStore
from app.utils.types import MediaType

class TMDBCache:
    def __init__(self):
        self.redis = RedisStore()

    def get_tmdb_info(self, mtype: MediaType, tmdbid: str, language: str = None) -> Optional[Any]:
        """从缓存获取TMDB信息，支持字典和对象"""
        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        cache_key = f"tmdb:{mtype.value}:{tmdbid}:{language or 'default'}"
        cached = self.redis.get(cache_key)
        if cached:
            try:
                result = pickle.loads(cached)
                log.debug(f"从Redis缓存命中TMDB信息: {cache_key}")
                return result
            except:
                log.debug(f"从Redis缓存命中TMDB信息(原始值): {cache_key}")
                return cached
        return None

    def set_tmdb_info(self, mtype: MediaType, tmdbid: str, info: Any, 
                     language: str = None, ttl: int = 3600) -> None:
        """缓存TMDB信息，支持字典和对象，默认1小时"""
        if mtype == MediaType.ANIME:
            mtype = MediaType.TV

        cache_key = f"tmdb:{mtype.value}:{tmdbid}:{language or 'default'}"
        # 其他类型则序列化存储
        value = pickle.dumps(info)
        self.redis.set(cache_key, value, ex=ttl)
        log.debug(f"已缓存TMDB信息到Redis: {cache_key}")

    def get_media_info(self, title: str, year: str = None, 
                      mtype: MediaType = None) -> Optional[Any]:
        """从缓存获取媒体信息，支持字典和对象"""
        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        cache_key = self._get_media_cache_key(title, year, mtype)
        cached = self.redis.get(cache_key)
        if cached:
            try:
                # 尝试反序列化对象
                result = pickle.loads(cached)
                log.debug(f"从Redis缓存命中媒体信息: {cache_key}")
                return result
            except:
                # 如果反序列化失败，直接返回原始值(兼容旧字典数据)
                log.debug(f"从Redis缓存命中媒体信息(原始值): {cache_key}")
                return cached
        return None

    def set_media_info(self, title: str, info: Any, 
                      year: str = None, mtype: MediaType = None, 
                      ttl: int = 3600*12) -> None:
        """缓存媒体信息，支持字典和对象，默认1小时"""
        if mtype == MediaType.ANIME:
            mtype = MediaType.TV
        cache_key = self._get_media_cache_key(title, year, mtype)
        value = pickle.dumps(info)
        self.redis.set(cache_key, value, ex=ttl)
        log.debug(f"已缓存媒体信息到Redis: {cache_key}")

    def _get_media_cache_key(self, title: str, year: str = None, 
                           mtype: MediaType = None) -> str:
        """生成媒体信息缓存键"""
        parts = ["media", title]
        if year:
            parts.append(year)
        if mtype:
            parts.append(mtype.value)
        return ":".join(parts)

    def clear_tmdb_cache(self, tmdbid: str) -> None:
        """清除指定TMDB ID的所有缓存"""
        pattern = f"tmdb:*:{tmdbid}:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
            log.debug(f"已清除TMDB ID {tmdbid} 的所有缓存")

    def clear_media_cache(self, title: str) -> None:
        """清除指定标题的所有媒体缓存"""
        pattern = f"media:{title}:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
            log.debug(f"已清除标题 {title} 的所有媒体缓存")
