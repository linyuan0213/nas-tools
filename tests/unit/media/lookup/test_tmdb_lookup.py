"""TMDB lookup 工具函数测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.mediatypes import MediaType
from app.infrastructure.cache_system import get_cache_manager
from app.media.lookup.tmdb_lookup import TmdbLookup
from app.media.models import MediaInfo
from app.media.parser import RegexParser


class TestNegativeLookupCache:
    """未命中结果应被负缓存，避免每次重复查 TMDB."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache = get_cache_manager().get("tmdb_lookup")
        if cache is not None:
            cache.clear()

    def test_not_found_is_cached(self):
        parser = RegexParser()
        lookup = TmdbLookup(client=MagicMock())
        parsed = parser.parse("NegativeCacheOnlyTitle 1999")
        assert parsed is not None

        with patch.object(lookup, "_lookup_tmdb", return_value=None) as mock_lookup:
            assert lookup.lookup(parsed) is None
            assert mock_lookup.call_count >= 1
            first_call_count = mock_lookup.call_count

            # 第二次应命中负缓存，不再发起查询
            assert lookup.lookup(parsed) is None
            assert mock_lookup.call_count == first_call_count

    def test_negative_cache_expires(self):
        parser = RegexParser()
        lookup = TmdbLookup(client=MagicMock())
        parsed = parser.parse("NegativeCacheExpireTitle 2001")
        assert parsed is not None

        with patch.object(lookup, "_lookup_tmdb", return_value=None) as mock_lookup:
            assert lookup.lookup(parsed) is None
            first_call_count = mock_lookup.call_count

            # 直接改写缓存 TTL 为 0 模拟过期
            key = (
                f"lookup:{parsed.title_cn or ''}|{parsed.title_en or ''}|{parsed.year or ''}"
                f"|{parsed.season or ''}|{parsed.type.value if parsed.type else ''}|"
            )
            lookup._lookup_cache.set(key, False, ttl=0)
            assert lookup.lookup(parsed) is None
            assert mock_lookup.call_count > first_call_count


class TestMergeMediaInfo:
    """测试 merge_media_info 合并媒体信息."""

    def test_merge_media_info_copies_image_fields(self):
        """搜索结果缺少图片时应从原始匹配媒体复制图片字段."""
        target = MediaInfo(
            title="攻壳机动队",
            type=MediaType.TV,
            year="2026",
            tmdb_id=123456,
        )
        source = MediaInfo(
            title="攻壳机动队",
            type=MediaType.TV,
            year="2026",
            tmdb_id=123456,
            poster_path="https://image.tmdb.org/t/p/w500/abc.jpg",
            backdrop_path="https://image.tmdb.org/t/p/w1280/xyz.jpg",
            fanart_backdrop="https://fanart.tv/123.jpg",
        )

        result = TmdbLookup.merge_media_info(target, source)

        assert result.poster_path == "https://image.tmdb.org/t/p/w500/abc.jpg"
        assert result.backdrop_path == "https://image.tmdb.org/t/p/w1280/xyz.jpg"
        assert result.fanart_backdrop == "https://fanart.tv/123.jpg"

    def test_merge_media_info_keeps_target_image(self):
        """目标本身有图片时保留目标的图片."""
        target = MediaInfo(
            title="攻壳机动队",
            type=MediaType.TV,
            poster_path="https://target.poster.jpg",
        )
        source = MediaInfo(
            title="攻壳机动队",
            type=MediaType.TV,
            poster_path="https://source.poster.jpg",
        )

        result = TmdbLookup.merge_media_info(target, source)

        assert result.poster_path == "https://target.poster.jpg"

    def test_merge_media_info_returns_target_when_source_is_none(self):
        """source 为空时返回 target."""
        target = MediaInfo(title="Test", type=MediaType.MOVIE)
        assert TmdbLookup.merge_media_info(target, None) is target

    def test_merge_media_info_returns_target_when_target_is_none(self):
        """target 为空时返回 target."""
        source = MediaInfo(title="Test", type=MediaType.MOVIE)
        assert TmdbLookup.merge_media_info(None, source) is None
