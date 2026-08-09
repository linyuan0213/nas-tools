"""专用缓存 TTL 单元测试."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.infrastructure.cache_system.caches import (
    CategoryLoadCache,
    ConfigLoadCache,
    MediaInfoCache,
    OpenAISessionCache,
    SearchResultCache,
    SiteInfoCache,
    TokenCache,
    WordsProcessCache,
)


class TestTypedCacheTTL:
    """测试各业务缓存默认 TTL."""

    @pytest.mark.parametrize(
        ("cache_cls", "expected_ttl", "maxsize"),
        [
            (MediaInfoCache, 24 * 3600, 1000),
            (SearchResultCache, 3600, 500),
            (SiteInfoCache, 6 * 3600, 100),
            (TokenCache, 7 * 24 * 3600, 512),
            (ConfigLoadCache, 600, 1),
            (CategoryLoadCache, 600, 2),
            (OpenAISessionCache, 30 * 24 * 3600, 200),
            (WordsProcessCache, 24 * 3600, 1000),
        ],
    )
    def test_default_ttl_and_maxsize(self, cache_cls, expected_ttl, maxsize):
        cache = cache_cls()
        assert cache._adapter._default_ttl == expected_ttl
        assert cache._adapter._maxsize == maxsize

    def test_set_uses_default_ttl(self):
        cache = MediaInfoCache()
        cache.set("k", "v")
        ttl = cache._adapter.ttl("k")
        assert ttl > 0
        assert ttl <= 24 * 3600

    def test_set_accepts_custom_ttl(self):
        cache = MediaInfoCache()
        cache.set("k", "v", ttl=1)
        assert cache.get("k") == "v"
        time.sleep(1.1)
        assert cache.get("k") is None

    def test_search_result_expires(self):
        cache = SearchResultCache()
        cache.set("k", "v", ttl=1)
        assert cache.get("k") == "v"
        time.sleep(1.1)
        assert cache.get("k") is None

    def test_site_info_default_ttl(self):
        cache = SiteInfoCache()
        cache.set("k", "v")
        ttl = cache._adapter.ttl("k")
        assert 0 < ttl <= 6 * 3600


class TestRedisCacheAdapterScopedClear:
    """RedisCacheAdapter 键命名空间与安全清理测试"""

    @staticmethod
    def _make_fake_redis():
        class FakeRedis:
            def __init__(self):
                self.data = {}
                self.deleted = []

            def is_available(self):
                return True

            def set(self, key, value, ex=None):
                self.data[key] = value

            def get(self, key):
                return self.data.get(key)

            def exists(self, key):
                return key in self.data

            def delete(self, *keys):
                for k in keys:
                    self.data.pop(k, None)
                    self.deleted.append(k)

            def keys(self, pattern="*"):
                import fnmatch

                return [k for k in self.data if fnmatch.fnmatch(k, pattern)]

            def ttl(self, key):
                return -1

            def expire(self, key, seconds):
                return True

        return FakeRedis()

    def test_clear_only_deletes_own_namespace(self):
        from app.infrastructure.cache_system.adapters import RedisCacheAdapter

        store = self._make_fake_redis()
        with patch("app.infrastructure.redis.RedisStore", return_value=store):
            adapter = RedisCacheAdapter(name="mytest")

            adapter.set("k1", "v1")
            store.set("cache:other:k2", "v2")  # 另一个缓存的键
            store.set("nexus_media:message_queue", "stream")  # 消息队列等公共数据

            adapter.clear()

            assert adapter.get("k1") is None
            assert store.exists("cache:other:k2")  # 其他命名空间不受影响
            assert store.exists("nexus_media:message_queue")  # 公共数据不受影响

    def test_keys_are_namespaced(self):
        from app.infrastructure.cache_system.adapters import RedisCacheAdapter

        store = self._make_fake_redis()
        with patch("app.infrastructure.redis.RedisStore", return_value=store):
            adapter = RedisCacheAdapter(name="mytest")

            adapter.set("a", "v1")
            adapter.set("b", "v2")
            assert "cache:mytest:a" in store.data
            assert "cache:mytest:b" in store.data
            assert "a" not in store.data
            assert set(adapter.keys("*")) == {"a", "b"}
