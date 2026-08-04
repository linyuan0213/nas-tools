"""测试综合评分引擎 + 批量关键词检测"""

import pytest

from app.media.lookup.tmdb_lookup import _BATCH_KEYWORDS_RE
from app.media.lookup.tmdb_search import _STOP_TOKENS, _score_fuzzy_match, _tokenize


class TestScoreFuzzyMatch:
    def test_exact_name_match(self):
        score = _score_fuzzy_match(
            "Ghost In The Shell",
            {"number_of_episodes": 26, "number_of_seasons": 2},
            ["Ghost in the Shell", "攻壳机动队"],
        )
        assert score > 0.95

    def test_fuzzy_name_different_score(self):
        high = _score_fuzzy_match(
            "Ghost In The Shell S.A.C. 2Nd Gig",
            {"number_of_episodes": 52, "number_of_seasons": 2, "seasons": []},
            ["Ghost in the Shell: S.A.C. 2nd GIG", "攻壳机动队"],
        )
        low = _score_fuzzy_match(
            "Ghost In The Shell S.A.C. 2Nd Gig",
            {"number_of_episodes": 10, "number_of_seasons": 1, "seasons": []},
            ["Ghost in the Shell: S.A.C. 2nd GIG - Individual Eleven"],
        )
        assert high > low, f"精确匹配应高于带后缀的匹配: {high:.3f} vs {low:.3f}"

    def test_season_bonus_matters(self):
        with_season = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 10, "number_of_seasons": 1, "seasons": [{"season_number": 2, "episode_count": 12}]},
            ["Test Show"],
            season_number=2,
        )
        without_season = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 10, "number_of_seasons": 1, "seasons": []},
            ["Test Show"],
            season_number=2,
        )
        assert with_season > without_season, "有目标季号的条目得分应更高"

    def test_season_penalty_for_mismatch(self):
        base = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 10, "number_of_seasons": 1, "seasons": []},
            ["Test Show"],
        )
        penalty = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 10, "number_of_seasons": 1, "seasons": []},
            ["Test Show"],
            season_number=3,
        )
        assert penalty < base, "季号不匹配应有惩罚"

    def test_established_bonus(self):
        many_eps = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 52, "number_of_seasons": 2},
            ["Test Show"],
        )
        few_eps = _score_fuzzy_match(
            "Test Show",
            {"number_of_episodes": 10, "number_of_seasons": 1},
            ["Test Show"],
        )
        assert many_eps > few_eps, "多集数条目应获得已完结加分"

    def test_keyword_bonus(self):
        with_kw = _score_fuzzy_match(
            "Ghost In The Shell SAC 2045",
            {"number_of_episodes": 24, "number_of_seasons": 2},
            ["Ghost in the Shell: SAC_2045", "攻壳机动队 SAC_2045"],
        )
        no_kw = _score_fuzzy_match(
            "Ghost In The Shell",
            {"number_of_episodes": 24, "number_of_seasons": 2},
            ["Ghost in the Shell", "攻壳机动队"],
        )
        assert with_kw > no_kw, "有关键词重叠的条目得分应更高"


class TestTokenize:
    def test_tokenize_simple(self):
        tokens = _tokenize("Ghost In The Shell SAC 2045")
        assert "GHOST" in tokens
        assert "SHELL" in tokens
        assert "SAC" in tokens
        assert "2045" in tokens

    def test_tokenize_stopword_filtered(self):
        tokens = _tokenize("The Ghost In The Shell") - _STOP_TOKENS
        assert "GHOST" in tokens
        assert "SHELL" in tokens
        assert "THE" not in tokens


class TestBatchKeywordsRE:
    BATCH_PATTERNS = [
        ("[POPGO][Ghost][S.A.C._2nd_GIG][COMPLETE][1080P]", True),
        ("[Group] Anime Title 全集 [BD 1080p]", True),
        ("[Group] Anime 合集 BDRip", True),
        ("[Group] Show S1 PACK 1080p", True),
        ("[Group] Movie BATCH HEVC", True),
        ("[Group] Season 3 COLLECTION", True),
        ("[Group] 全季 1080p", True),
        ("[Group] Just A Movie [1080P]", False),
        ("[LoliHouse] Ghost in the Shell - 01 [WebRip]", False),
        ("[POPGO][S.A.C._2nd_GIG][BDRIP][1080P]", False),
        ("Complete Series BluRay", True),
    ]

    @pytest.mark.parametrize("title,expected", BATCH_PATTERNS)
    def test_batch_keyword_detection(self, title, expected):
        result = bool(_BATCH_KEYWORDS_RE.search(title))
        assert result == expected, f"title={title!r}"


class TestSearchTvBySeasonGuard:
    """search_tv_by_season 首轮命中必须校验目标季存在（同名真人剧 vs 动漫回归）"""

    def _make_search(self, tvs, details):
        from unittest.mock import MagicMock

        from app.media.lookup.tmdb_search import TmdbSearch

        client = MagicMock()
        client.search.tv_shows.return_value = tvs
        client.get_blacklist.return_value = []
        search = TmdbSearch(client)
        search._get_detail = lambda tmdbid, mtype: details.get(tmdbid, {})
        search._fetch_allnames = lambda mtype, tmdb_id: (details.get(tmdb_id, {}), [])
        return search

    def test_skip_candidate_without_requested_season(self):
        live_action = {
            "id": 263121,
            "name": "更衣人偶坠入爱河",
            "original_name": "その着せ替え人形は恋をする",
            "first_air_date": "2024-10-09",
        }
        details = {
            263121: {
                "id": 263121,
                "seasons": [{"season_number": 1, "air_date": "2024-10-09", "episode_count": 9}],
                "number_of_episodes": 9,
            }
        }
        search = self._make_search([live_action], details)
        result = search.search_tv_by_season("更衣人偶坠入爱河", "2024", 2)
        assert not result, "无 S2 的同名条目不应命中按季搜索"

    def test_hit_candidate_with_requested_season(self):
        anime = {
            "id": 123249,
            "name": "更衣人偶坠入爱河",
            "original_name": "その着せ替え人形は恋をする",
            "first_air_date": "2022-01-09",
        }
        details = {
            123249: {
                "id": 123249,
                "seasons": [
                    {"season_number": 1, "air_date": "2022-01-09", "episode_count": 12},
                    {"season_number": 2, "air_date": "2024-07-01", "episode_count": 12},
                ],
                "number_of_episodes": 24,
            }
        }
        search = self._make_search([anime], details)
        result = search.search_tv_by_season("更衣人偶坠入爱河", "2022", 2)
        assert result and result.get("id") == 123249
