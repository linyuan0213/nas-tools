"""
缓存适配器实现
支持内存缓存和Redis缓存
"""

import fnmatch
import pickle
import threading
from collections import OrderedDict
from typing import Any

import log

from .base import CacheAdapter, CacheEntry
from .events import CacheEvent, CacheEventType, get_event_manager

# 获取事件管理器实例
_event_manager = get_event_manager()


def _emit_cache_event(event: CacheEvent) -> None:
    """仅在存在监听器时触发缓存事件，避免高频空转。"""
    if _event_manager._global_listeners or any(_event_manager._listeners.values()):
        _event_manager.emit(event)


def get_cache_value(cache_adapter, key: str) -> Any:
    """
    获取缓存值，返回 (found, value) 元组
    found: True 表示缓存命中，False 表示缓存未命中
    value: 缓存值（当 found 为 True 时）
    """
    value = cache_adapter.get(key)
    if value is None:
        # 检查是缓存不存在/过期，还是缓存值就是 None
        if not cache_adapter.exists(key):
            return False, None
    return True, value


class MemoryCacheAdapter(CacheAdapter):
    """内存缓存适配器 - 使用LRU策略"""

    def __init__(self, maxsize: int = 1000, name: str = "memory", default_ttl: int | None = None):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._maxsize = maxsize
        self._name = name
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._stats = {"hits": 0, "misses": 0, "sets": 0, "deletes": 0, "evictions": 0}

    def get(self, key: str) -> Any | None:
        """获取缓存值"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                # 触发MISS事件
                _emit_cache_event(CacheEvent(event_type=CacheEventType.MISS, cache_name=self._name, key=key))
                return None

            if entry.is_expired():
                del self._cache[key]
                self._stats["misses"] += 1
                # 触发EXPIRE事件
                _emit_cache_event(CacheEvent(event_type=CacheEventType.EXPIRE, cache_name=self._name, key=key))
                return None

            # LRU: 移动到末尾（最近使用）
            self._cache.move_to_end(key)
            self._stats["hits"] += 1
            # 触发GET和HIT事件
            _emit_cache_event(
                CacheEvent(event_type=CacheEventType.GET, cache_name=self._name, key=key, value=entry.value)
            )
            _emit_cache_event(
                CacheEvent(event_type=CacheEventType.HIT, cache_name=self._name, key=key, value=entry.value)
            )
            return entry.value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置缓存值"""
        if ttl is None:
            ttl = self._default_ttl
        with self._lock:
            # 如果键已存在，先删除以便更新位置
            if key in self._cache:
                del self._cache[key]

            # 检查是否需要淘汰
            evicted = False
            while len(self._cache) >= self._maxsize:
                self._evict_oldest()
                evicted = True

            self._cache[key] = CacheEntry(value, ttl)
            self._stats["sets"] += 1

            # 触发SET事件
            _emit_cache_event(
                CacheEvent(event_type=CacheEventType.SET, cache_name=self._name, key=key, value=value, ttl=ttl)
            )

            # 如果发生了驱逐，触发EVICT事件
            if evicted:
                _emit_cache_event(CacheEvent(event_type=CacheEventType.EVICT, cache_name=self._name))

            return True

    def _evict_oldest(self):
        """淘汰最旧的条目"""
        if self._cache:
            oldest_key = next(iter(self._cache))
            oldest_entry = self._cache[oldest_key]
            del self._cache[oldest_key]
            self._stats["evictions"] += 1
            # 触发EVICT事件
            _emit_cache_event(
                CacheEvent(
                    event_type=CacheEventType.EVICT, cache_name=self._name, key=oldest_key, value=oldest_entry.value
                )
            )

    def delete(self, key: str) -> bool:
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                del self._cache[key]
                self._stats["deletes"] += 1
                # 触发DELETE事件
                _emit_cache_event(
                    CacheEvent(event_type=CacheEventType.DELETE, cache_name=self._name, key=key, value=entry.value)
                )
                return True
            return False

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                return False
            return True

    def clear(self) -> bool:
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
            # 触发CLEAR事件
            _emit_cache_event(CacheEvent(event_type=CacheEventType.CLEAR, cache_name=self._name))
            return True

    def keys(self, pattern: str = "*") -> list[str]:
        """获取匹配模式的键列表"""
        with self._lock:
            if pattern == "*":
                keys = list(self._cache.keys())
            else:
                keys = [k for k in self._cache if fnmatch.fnmatch(k, pattern)]
            # 清理过期条目并返回有效键
            result = []
            for k in keys:
                entry = self._cache[k]
                if entry.is_expired():
                    del self._cache[k]
                else:
                    result.append(k)
            return result

    def ttl(self, key: str) -> int:
        """获取键的剩余生存时间"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return -2
            return entry.get_remaining_ttl()

    def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired():
                return False
            entry.ttl = seconds
            entry.created_at = __import__("time").time()
            return True

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                "name": self._name,
                "type": "memory",
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": f"{hit_rate:.2%}",
                "sets": self._stats["sets"],
                "deletes": self._stats["deletes"],
                "evictions": self._stats["evictions"],
            }


class RedisCacheAdapter(CacheAdapter):
    """Redis缓存适配器 - Redis不可用时自动回退到内存缓存"""

    def __init__(self, name: str = "redis", default_ttl: int | None = None, fallback_maxsize: int = 2000):
        self._name = name
        self._key_prefix = f"cache:{name}:"
        self._default_ttl = default_ttl
        self._redis = None
        self._fallback = MemoryCacheAdapter(maxsize=fallback_maxsize, name=f"{name}_fallback", default_ttl=default_ttl)
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0,
            "fallback_hits": 0,
            "fallback_sets": 0,
        }
        self._lock = threading.Lock()
        self._init_redis()

    def _init_redis(self):
        """初始化Redis连接"""
        try:
            # 延迟导入：测试 mock 依赖 + 避免模块加载即连接 Redis
            from app.infrastructure.redis import RedisStore  # noqa: PLC0415

            store = RedisStore()
            if store.is_available():
                self._redis = store
                log.debug(f"[Cache]Redis适配器初始化成功: {self._name}")
            else:
                log.info(f"[Cache]Redis不可用，使用内存回退: {self._name}")
                self._redis = None
        except Exception as e:
            log.info(f"[Cache]Redis适配器初始化失败，使用内存回退: {e}")
            self._redis = None

    def _ensure_connection(self) -> bool:
        """确保Redis连接可用"""
        if self._redis is not None:
            try:
                if self._redis.is_available():
                    return True
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Cache]忽略异常: {e}")
            self._redis = None
        # 尝试重连
        self._init_redis()
        return self._redis is not None

    def _redis_key(self, key: str) -> str:
        """Redis 键加缓存命名空间前缀，避免清缓存误删消息队列/调度器等公共数据"""
        return f"{self._key_prefix}{key}"

    def get(self, key: str) -> Any | None:
        """获取缓存值 - 先查Redis，失败回退到内存"""
        if self._ensure_connection() and self._redis is not None:
            try:
                data = self._redis.get(self._redis_key(key))
                if data is not None:
                    try:
                        value = pickle.loads(data)  # nosec B301
                    except Exception as e:  # noqa: BLE001
                        log.debug(f"[Cache]反序列化失败 {key}: {e}")
                        value = data
                    with self._lock:
                        self._stats["hits"] += 1
                    _emit_cache_event(
                        CacheEvent(event_type=CacheEventType.HIT, cache_name=self._name, key=key, value=value)
                    )
                    return value
            except Exception as e:
                log.debug(f"[Cache]Redis get 失败，回退内存 {key}: {e}")
                with self._lock:
                    self._stats["errors"] += 1

        # 回退到内存缓存
        value = self._fallback.get(key)
        if value is not None:
            with self._lock:
                self._stats["fallback_hits"] += 1
        else:
            with self._lock:
                self._stats["misses"] += 1
            _emit_cache_event(CacheEvent(event_type=CacheEventType.MISS, cache_name=self._name, key=key))
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置缓存值 - 同时写入Redis和内存回退"""
        if ttl is None:
            ttl = self._default_ttl

        redis_ok = False
        if self._ensure_connection() and self._redis is not None:
            try:
                data = pickle.dumps(value)
                self._redis.set(self._redis_key(key), data, ex=ttl)
                with self._lock:
                    self._stats["sets"] += 1
                redis_ok = True
            except Exception as e:
                log.debug(f"[Cache]Redis set 失败 {key}: {e}")
                with self._lock:
                    self._stats["errors"] += 1

        # 无论Redis是否成功，都写入内存回退
        fallback_ok = self._fallback.set(key, value, ttl)
        if fallback_ok:
            with self._lock:
                self._stats["fallback_sets"] += 1

        if redis_ok or fallback_ok:
            _emit_cache_event(
                CacheEvent(event_type=CacheEventType.SET, cache_name=self._name, key=key, value=value, ttl=ttl)
            )
            return True
        return False

    def delete(self, key: str) -> bool:
        """删除缓存 - 同时删除Redis和内存回退"""
        redis_ok = False
        if self._ensure_connection() and self._redis is not None:
            try:
                self._redis.delete(self._redis_key(key))
                with self._lock:
                    self._stats["deletes"] += 1
                redis_ok = True
            except Exception as e:
                log.debug(f"[Cache]Redis delete 失败 {key}: {e}")

        fallback_ok = self._fallback.delete(key)

        if redis_ok or fallback_ok:
            _emit_cache_event(CacheEvent(event_type=CacheEventType.DELETE, cache_name=self._name, key=key))
            return True
        return False

    def exists(self, key: str) -> bool:
        """检查键是否存在 - 先查Redis，再查内存回退"""
        if self._ensure_connection() and self._redis is not None:
            try:
                return self._redis.exists(self._redis_key(key))
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Cache]忽略异常: {e}")
        return self._fallback.exists(key)

    def clear(self) -> bool:
        """清空本缓存命名空间下的键，不影响消息队列/调度器等其他 Redis 数据"""
        if self._ensure_connection() and self._redis is not None:
            try:
                keys = self._redis.keys(f"{self._key_prefix}*")
                if keys:
                    self._redis.delete(*keys)
            except Exception as e:
                log.debug(f"[Cache]Redis clear 失败: {e}")

        self._fallback.clear()

        _emit_cache_event(CacheEvent(event_type=CacheEventType.CLEAR, cache_name=self._name))
        return True

    def keys(self, pattern: str = "*") -> list[str]:
        """获取匹配模式的键列表"""
        redis_keys = []
        if self._ensure_connection() and self._redis is not None:
            try:
                redis_keys = self._redis.keys(f"{self._key_prefix}{pattern}")
                # 去掉前缀返回原始键名
                redis_keys = [k[len(self._key_prefix) :] for k in redis_keys]
            except Exception as e:
                log.debug(f"[Cache]Redis keys 失败: {e}")

        fallback_keys = self._fallback.keys(pattern)
        # 合并去重
        return list(set(redis_keys + fallback_keys))

    def ttl(self, key: str) -> int:
        """获取键的剩余生存时间"""
        if self._ensure_connection() and self._redis is not None:
            try:
                return self._redis.ttl(self._redis_key(key))
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Cache]忽略异常: {e}")
        return self._fallback.ttl(key)

    def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间"""
        redis_ok = False
        if self._ensure_connection() and self._redis is not None:
            try:
                self._redis.expire(self._redis_key(key), seconds)
                redis_ok = True
            except Exception as e:
                log.debug(f"[Cache]Redis expire 失败 {key}: {e}")

        fallback_ok = self._fallback.expire(key, seconds)
        return redis_ok or fallback_ok

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                "name": self._name,
                "type": "redis",
                "connected": self._redis is not None,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": f"{hit_rate:.2%}",
                "sets": self._stats["sets"],
                "deletes": self._stats["deletes"],
                "errors": self._stats["errors"],
                "fallback": self._fallback.get_stats(),
                "fallback_hits": self._stats["fallback_hits"],
                "fallback_sets": self._stats["fallback_sets"],
            }


class TieredCacheAdapter(CacheAdapter):
    """分层缓存适配器 - L1(内存) + L2(Redis)"""

    def __init__(self, memory_maxsize: int = 1000, name: str = "tiered", default_ttl: int | None = None):
        self._l1 = MemoryCacheAdapter(maxsize=memory_maxsize, name=f"{name}_l1", default_ttl=default_ttl)
        self._l2 = RedisCacheAdapter(name=f"{name}_l2", default_ttl=default_ttl)
        self._name = name
        self._stats = {"l1_hits": 0, "l2_hits": 0, "misses": 0}

    def get(self, key: str) -> Any | None:
        """获取缓存值 - 先查L1，再查L2"""
        # 先查L1
        value = self._l1.get(key)
        if value is not None:
            self._stats["l1_hits"] += 1
            return value

        # 再查L2
        value = self._l2.get(key)
        if value is not None:
            self._stats["l2_hits"] += 1
            # 回填L1
            self._l1.set(key, value)
            return value

        self._stats["misses"] += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """设置缓存值 - 同时设置L1和L2"""
        l1_result = self._l1.set(key, value, ttl)
        l2_result = self._l2.set(key, value, ttl)
        return l1_result or l2_result

    def delete(self, key: str) -> bool:
        """删除缓存"""
        l1_result = self._l1.delete(key)
        l2_result = self._l2.delete(key)
        return l1_result or l2_result

    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return self._l1.exists(key) or self._l2.exists(key)

    def clear(self) -> bool:
        """清空所有缓存"""
        l1_result = self._l1.clear()
        l2_result = self._l2.clear()
        return l1_result and l2_result

    def keys(self, pattern: str = "*") -> list[str]:
        """获取匹配模式的键列表"""
        # 合并L1和L2的键
        l1_keys = set(self._l1.keys(pattern))
        l2_keys = set(self._l2.keys(pattern))
        return list(l1_keys | l2_keys)

    def ttl(self, key: str) -> int:
        """获取键的剩余生存时间"""
        # 优先使用L1的TTL
        l1_ttl = self._l1.ttl(key)
        if l1_ttl >= 0:
            return l1_ttl
        return self._l2.ttl(key)

    def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间"""
        l1_result = self._l1.expire(key, seconds)
        l2_result = self._l2.expire(key, seconds)
        return l1_result or l2_result

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        total = sum(self._stats.values())
        return {
            "name": self._name,
            "type": "tiered",
            "l1": self._l1.get_stats(),
            "l2": self._l2.get_stats(),
            "l1_hits": self._stats["l1_hits"],
            "l2_hits": self._stats["l2_hits"],
            "misses": self._stats["misses"],
            "total_requests": total,
        }
