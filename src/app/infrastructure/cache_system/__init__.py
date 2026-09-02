"""
统一缓存系统

提供统一的缓存接口，支持多种后端存储（内存、Redis等）
"""

from .adapters import MemoryCacheAdapter, RedisCacheAdapter, TieredCacheAdapter
from .cache_manager import CacheManager
from .caches import (
    CategoryLoadCache,
    ConfigLoadCache,
    MediaInfoCache,
    OpenAISessionCache,
    SearchResultCache,
    SiteInfoCache,
    TMDBCache,
    TokenCache,
)
from .compat import cacheman
from .decorators import cached, cached_with_lock, lru_cache_with_ttl
from .events import (
    CacheEvent,
    CacheEventManager,
    CacheEventType,
    get_event_manager,
    on_cache_event,
)
from .manager import get_cache_manager
from .utils import CacheKeyBuilder

__all__ = [
    # 核心管理器
    "CacheManager",
    # 适配器
    "MemoryCacheAdapter",
    "RedisCacheAdapter",
    # 装饰器
    "cached",
    "cached_with_lock",
    "lru_cache_with_ttl",
    # 专用缓存类
    "TMDBCache",
    "MediaInfoCache",
    "SearchResultCache",
    "TokenCache",
    "ConfigLoadCache",
    "CategoryLoadCache",
    "OpenAISessionCache",
    "SiteInfoCache",
    # 专用缓存实例
    "MediaInfoCache",
    "SearchResultCache",
    "SiteInfoCache",
    "TokenCache",
    "ConfigLoadCache",
    "CategoryLoadCache",
    "OpenAISessionCache",
    # 工具
    "CacheKeyBuilder",
    "get_cache_manager",
    # 缓存事件
    "CacheEventType",
    "CacheEvent",
    "CacheEventManager",
    "get_event_manager",
    "on_cache_event",
    # 兼容旧接口
    "cacheman",
]

# 初始化全局缓存管理器并创建默认缓存
_cache_manager = get_cache_manager()
_cache_manager.create_memory_cache("tmdb_supply", maxsize=500)
_cache_manager.create_memory_cache("media_info", maxsize=1000)
_cache_manager.create_memory_cache("search_result", maxsize=500)
_cache_manager.create_memory_cache("token", maxsize=512)
_cache_manager.create_memory_cache("config_load", maxsize=1)
_cache_manager.create_memory_cache("category_load", maxsize=2)
_cache_manager.create_memory_cache("site_info", maxsize=100)
# 下载器种子平均上传速度缓存：up_speed_avg 为长期平均值，避免 completed 种子多时逐种拉取 properties
_cache_manager.create_memory_cache("downloader_up_avg", maxsize=10000, ttl=600)
_cache_manager.create_redis_cache("tmdb")

# OpenAI 会话缓存使用分层缓存：L1 内存 + L2 Redis
# 重启后对话历史不会丢失
_openai_session_adapter = TieredCacheAdapter(memory_maxsize=200, name="openai_session", default_ttl=None)

# 创建专用缓存实例
MediaInfoCache = MediaInfoCache(_cache_manager.get("media_info"))
SearchResultCache = SearchResultCache(_cache_manager.get("search_result"))
SiteInfoCache = SiteInfoCache(_cache_manager.get("site_info"))
TokenCache = TokenCache(_cache_manager.get("token"))
ConfigLoadCache = ConfigLoadCache(_cache_manager.get("config_load"))
CategoryLoadCache = CategoryLoadCache(_cache_manager.get("category_load"))
OpenAISessionCache = OpenAISessionCache(_openai_session_adapter)
