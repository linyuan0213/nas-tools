"""SubscribeMatcher 单元测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.mediatypes import MediaType
from app.media.identity.matcher import TargetMatcher
from app.media.identity.models import Work
from app.services.subscribe.matcher import SubscribeMatcher


def _make_media_info(mtype, title, year, tmdb_id=None):
    media_info = MagicMock()
    media_info.type = mtype
    media_info.title = title
    media_info.year = year
    media_info.tmdb_id = tmdb_id
    media_info.rev_string = title
    media_info.org_string = f"{title} {year}"
    media_info.get_name.return_value = title
    media_info.get_title_string.return_value = title
    media_info.get_season_string.return_value = "S01"
    media_info.get_season_episode_string.return_value = "S01 E01"
    media_info.site = "test_site"
    media_info.subtitle = ""
    return media_info


@pytest.fixture
def matcher():
    return SubscribeMatcher()


class TestSubscribeMatcher:
    def test_movie_torrent_does_not_match_tv_subscription(self, matcher):
        """电影种子不应匹配电视剧订阅."""
        media_info = _make_media_info(MediaType.MOVIE, "攻壳机动队", "1995")
        rss_tvs = {
            1: {
                "name": "攻壳机动队",
                "year": "2026",
                "season": "S01",
                "tmdbid": None,
                "fuzzy_match": False,
            }
        }

        match_flag, match_msg, match_info = matcher.match(
            media_info=media_info,
            rss_movies={},
            rss_tvs=rss_tvs,
            site_id="test_site",
            site_filter_rule=None,
            site_cookie="",
            site_parse=False,
            site_ua="",
            site_headers={},
            site_proxy=False,
        )
        assert match_flag is False

    def test_tv_torrent_matches_tv_subscription(self, matcher):
        """电视剧种子应匹配同名同年份电视剧订阅."""
        media_info = _make_media_info(MediaType.TV, "攻壳机动队", "2026")
        rss_tvs = {
            1: {
                "name": "攻壳机动队",
                "year": "2026",
                "season": "S01",
                "tmdbid": None,
                "fuzzy_match": False,
            }
        }

        match_flag, match_msg, match_info = matcher.match(
            media_info=media_info,
            rss_movies={},
            rss_tvs=rss_tvs,
            site_id="test_site",
            site_filter_rule=None,
            site_cookie="",
            site_parse=False,
            site_ua="",
            site_headers={},
            site_proxy=False,
        )
        assert match_flag is True
        assert match_info["name"] == "攻壳机动队"

    def test_anime_torrent_matches_tv_subscription(self, matcher):
        """动漫种子应匹配电视剧订阅."""
        media_info = _make_media_info(MediaType.ANIME, "攻壳机动队", "2026")
        rss_tvs = {
            1: {
                "name": "攻壳机动队",
                "year": "2026",
                "season": "S01",
                "tmdbid": None,
                "fuzzy_match": False,
            }
        }

        match_flag, match_msg, match_info = matcher.match(
            media_info=media_info,
            rss_movies={},
            rss_tvs=rss_tvs,
            site_id="test_site",
            site_filter_rule=None,
            site_cookie="",
            site_parse=False,
            site_ua="",
            site_headers={},
            site_proxy=False,
        )
        assert match_flag is True
        assert match_info["name"] == "攻壳机动队"

    def test_movie_torrent_matches_movie_subscription(self, matcher):
        """电影种子应匹配电影订阅."""
        media_info = _make_media_info(MediaType.MOVIE, "攻壳机动队", "1995")
        rss_movies = {
            1: {
                "name": "攻壳机动队",
                "year": "1995",
                "tmdbid": None,
                "fuzzy_match": False,
            }
        }

        match_flag, match_msg, match_info = matcher.match(
            media_info=media_info,
            rss_movies=rss_movies,
            rss_tvs={},
            site_id="test_site",
            site_filter_rule=None,
            site_cookie="",
            site_parse=False,
            site_ua="",
            site_headers={},
            site_proxy=False,
        )
        assert match_flag is True
        assert match_info["name"] == "攻壳机动队"

    def test_tv_torrent_does_not_match_movie_subscription(self, matcher):
        """电视剧种子不应匹配电影订阅."""
        media_info = _make_media_info(MediaType.TV, "攻壳机动队", "2026")
        rss_movies = {
            1: {
                "name": "攻壳机动队",
                "year": "1995",
                "tmdbid": None,
                "fuzzy_match": False,
            }
        }

        match_flag, match_msg, match_info = matcher.match(
            media_info=media_info,
            rss_movies=rss_movies,
            rss_tvs={},
            site_id="test_site",
            site_filter_rule=None,
            site_cookie="",
            site_parse=False,
            site_ua="",
            site_headers={},
            site_proxy=False,
        )
        assert match_flag is False

    def test_year_mismatch_blocks_fuzzy_match(self, matcher):
        media_info = _make_media_info(MediaType.MOVIE, "Ghost in the Shell", "1995")
        rss_movies = {1: {"name": "Ghost in the Shell", "year": "2026", "tmdbid": "255358", "fuzzy_match": True}}
        match_flag, _, _ = matcher.match(media_info, rss_movies, {}, "test_site", None, "", False, "", {}, False)
        assert match_flag is False

    def test_torrent_metadata_not_mutated_after_match(self, matcher):
        media_info = _make_media_info(MediaType.TV, "Ghost In The Shell", "2026", tmdb_id=0)
        rss_tvs = {1: {"name": "攻壳机动队", "year": "2026", "season": "S01", "tmdbid": "255358", "fuzzy_match": False}}
        o_title, o_year, o_type, o_tmdb = media_info.title, media_info.year, media_info.type, media_info.tmdb_id
        matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert media_info.title == o_title
        assert media_info.year == o_year
        assert media_info.type == o_type
        assert media_info.tmdb_id == o_tmdb


def _unified_target_matcher(works=None):
    index = MagicMock()
    if works:
        index.get_work.side_effect = lambda source, wid: works.get(wid)
    return TargetMatcher(graph=MagicMock(), index=index)


class TestUnifiedMatching:
    """ADR-014 P3：target_matcher 开启后订阅匹配走统一身份判等"""

    @pytest.fixture
    def matcher(self):
        return SubscribeMatcher()

    def test_same_tmdb_matches(self, matcher):
        """同一 tmdb_id → id_match 命中"""
        media_info = _make_media_info(MediaType.TV, "Ghost In The Shell", "2026", tmdb_id=255358)
        rss_tvs = {1: {"name": "攻壳机动队", "year": "2026", "season": "S01", "tmdbid": "255358", "fuzzy_match": False}}
        with (
            patch("app.services.subscribe.matcher.settings") as mock_settings,
            patch(
                "app.services.subscribe.matcher.get_target_matcher",
                return_value=_unified_target_matcher(),
            ),
        ):
            mock_settings.get.return_value = {"target_matcher": True}
            match_flag, match_msg, match_info = matcher.match(
                media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False
            )
        assert match_flag is True
        assert match_info["name"] == "攻壳机动队"

    def test_different_tmdb_rejected(self, matcher):
        """不同 tmdb_id 且无 franchise 关系 → 拒绝"""
        media_info = _make_media_info(MediaType.TV, "Ghost In The Shell", "2026", tmdb_id=62070)
        rss_tvs = {1: {"name": "攻壳机动队", "year": "2026", "season": "S01", "tmdbid": "255358", "fuzzy_match": False}}
        with (
            patch("app.services.subscribe.matcher.settings") as mock_settings,
            patch(
                "app.services.subscribe.matcher.get_target_matcher",
                return_value=_unified_target_matcher(),
            ),
        ):
            mock_settings.get.return_value = {"target_matcher": True}
            match_flag, _, _ = matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert match_flag is False

    def test_same_franchise_different_edition_rejected(self, matcher):
        """同 franchise 不同 edition（SAC_2045 vs 2026 新剧）→ 可解释拒绝"""
        works = {
            62070: Work(
                source="tmdb",
                work_id=62070,
                franchise="ghostintheshell",
                official_titles=["Ghost in the Shell SAC_2045"],
            ),
            255358: Work(
                source="tmdb",
                work_id=255358,
                franchise="ghostintheshell",
                official_titles=["Ghost in the Shell"],
            ),
        }
        media_info = _make_media_info(MediaType.TV, "Ghost In The Shell SAC_2045", "2020", tmdb_id=62070)
        rss_tvs = {1: {"name": "攻壳机动队", "year": "2026", "season": "S01", "tmdbid": "255358", "fuzzy_match": False}}
        with (
            patch("app.services.subscribe.matcher.settings") as mock_settings,
            patch(
                "app.services.subscribe.matcher.get_target_matcher",
                return_value=_unified_target_matcher(works),
            ),
        ):
            mock_settings.get.return_value = {"target_matcher": True}
            match_flag, _, _ = matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert match_flag is False


class TestFuzzyNameMatch:
    """fuzzy 分支：规范化子串匹配替代裸 re.search"""

    def test_regex_metachar_treated_as_literal(self, matcher):
        """订阅名含正则元字符 → 按字面子串匹配，不当作正则"""
        media_info = _make_media_info(MediaType.TV, "攻壳机动队", "2026")
        rss_tvs = {
            1: {"name": "攻壳机动队(2026)", "year": "2026", "season": "S01", "tmdbid": None, "fuzzy_match": True}
        }
        match_flag, _, _ = matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert match_flag is True

    def test_punct_differs_still_matches(self, matcher):
        """标点/大小写差异经归一化后仍匹配"""
        media_info = _make_media_info(MediaType.TV, "Ghost.In.The.Shell", "2026")
        rss_tvs = {
            1: {"name": "ghost in the shell", "year": "2026", "season": "S01", "tmdbid": None, "fuzzy_match": True}
        }
        match_flag, _, _ = matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert match_flag is True

    def test_name_not_in_title_rejected(self, matcher):
        """名称与种子标题无包含关系 → 拒绝"""
        media_info = _make_media_info(MediaType.TV, "Star Wars", "1977")
        rss_tvs = {1: {"name": "攻壳机动队", "year": "2026", "season": "S01", "tmdbid": None, "fuzzy_match": True}}
        match_flag, _, _ = matcher.match(media_info, {}, rss_tvs, "test_site", None, "", False, "", {}, False)
        assert match_flag is False
