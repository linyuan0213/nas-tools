"""解析缓存与站点延迟跟踪测试"""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.indexer.indexer import SiteLatencyTracker, _clamp_timeouts, _env_float
from app.media.parser.parse_cache import ParseCache


class TestParseCache:
    def _cache(self):
        c = ParseCache.__new__(ParseCache)
        c._cache = MagicMock()
        c._cache.get.return_value = None  # type: ignore[union-attr]
        return c

    def test_miss_then_hit(self):
        c = self._cache()
        title = "[LoliHouse] 穹庐下的魔女 / Tenmaku no Jaadugar - 04 [WebRip 1080p HEVC-10bit AAC]"
        first = c.parse(title)
        assert first.cn_name == "穹庐下的魔女"
        c._cache.set.assert_called_once()  # type: ignore[union-attr]
        # 命中：model_validate_json 独立副本
        c._cache.get.return_value = first.model_dump_json()  # type: ignore[union-attr]
        second = c.parse(title)
        assert second.cn_name == "穹庐下的魔女"
        assert second is not first  # 独立副本，防共享污染

    def test_hit_returns_independent_copy(self):
        c = self._cache()
        from app.media.models import MediaInfo

        c._cache.get.return_value = MediaInfo(cn_name="测试").model_dump_json()  # type: ignore[union-attr]
        a = c.parse("x")
        b = c.parse("x")
        a.cn_name = "被改"
        assert b.cn_name == "测试"

    def test_key_includes_subtitle_and_mtype(self):
        k1 = ParseCache._key("t", None, None)
        k2 = ParseCache._key("t", "s", None)
        k3 = ParseCache._key("t", None, MediaType.TV)
        assert len({k1, k2, k3}) == 3


class TestSiteLatencyTracker:
    def _tracker(self):
        t = SiteLatencyTracker.__new__(SiteLatencyTracker)
        t._cache = _MemCache()  # type: ignore[assignment]
        return t

    def test_default_max_when_few_samples(self):
        t = self._tracker()
        indexer = MagicMock()
        indexer.name = "SlowSite"
        assert t.timeout_for(indexer) == 45.0

    def test_adaptive_shrinks_for_fast_site(self):
        t = self._tracker()
        indexer = MagicMock()
        indexer.name = "FastSite"
        for _ in range(5):
            t.record(indexer, 2.0)
        assert t.timeout_for(indexer) == 15.0  # p95*1.5=3.0 → clamp 到 MIN

    def test_slow_site_gets_less_than_max(self):
        t = self._tracker()
        indexer = MagicMock()
        indexer.name = "MidSite"
        for _ in range(5):
            t.record(indexer, 15.0)
        assert t.timeout_for(indexer) == 22.5  # 15*1.5

    def test_samples_capped(self):
        t = self._tracker()
        indexer = MagicMock()
        indexer.name = "X"
        for i in range(30):
            t.record(indexer, float(i))
        samples = t._cache.get(f"lat:{indexer.name}")
        assert len(samples or []) == 20


class TestSiteTimeoutEnv:
    def test_missing_env_uses_default(self, monkeypatch):
        monkeypatch.delenv("NEXUS_MEDIA_INDEXER_TIMEOUT", raising=False)
        assert _env_float("NEXUS_MEDIA_INDEXER_TIMEOUT", 45.0) == 45.0

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEXUS_MEDIA_INDEXER_TIMEOUT", "abc")
        assert _env_float("NEXUS_MEDIA_INDEXER_TIMEOUT", 45.0) == 45.0

    def test_empty_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEXUS_MEDIA_INDEXER_TIMEOUT", "")
        assert _env_float("NEXUS_MEDIA_INDEXER_TIMEOUT", 45.0) == 45.0

    def test_non_positive_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEXUS_MEDIA_INDEXER_TIMEOUT", "0")
        assert _env_float("NEXUS_MEDIA_INDEXER_TIMEOUT", 45.0) == 45.0

    def test_valid_env_parsed(self, monkeypatch):
        monkeypatch.setenv("NEXUS_MEDIA_INDEXER_TIMEOUT", "60")
        assert _env_float("NEXUS_MEDIA_INDEXER_TIMEOUT", 45.0) == 60.0

    def test_min_above_max_aligns_to_max(self):
        assert _clamp_timeouts(60.0, 45.0) == (45.0, 45.0)


class _MemCache:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl=None):
        self._data[key] = value
        return True
