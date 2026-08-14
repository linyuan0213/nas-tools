"""测试 TMDB 客户端工具函数 — 多语言名称匹配"""

from app.domain.mediatypes import MediaType
from app.media.lookup.tmdb_client import (
    compare_tmdb_names,
    get_tmdb_chinese_title,
    update_tmdbinfo_cn_title,
)


class TestCompareTmdbNames:
    def test_exact_match(self):
        assert compare_tmdb_names("鬼灭之刃", ["鬼灭之刃"]) is True

    def test_simplified_traditional_match(self):
        assert compare_tmdb_names("進擊的巨人", ["进击的巨人"]) is True

    def test_taiwanese_input_match_cn(self):
        assert compare_tmdb_names("我的英雄學院", ["我的英雄学院"]) is True

    def test_english_case_insensitive(self):
        assert compare_tmdb_names("Jujutsu Kaisen", ["jujutsu kaisen"]) is True

    def test_substring_match(self):
        assert compare_tmdb_names("鬼灭之刃", ["鬼灭之刃"]) is True

    def test_similar_match(self):
        assert compare_tmdb_names("Kimetsu no Yaiba", ["Kimetsu no Yaiba"]) is True

    def test_short_name_skip(self):
        assert compare_tmdb_names("AB", ["ABCD"]) is False

    def test_no_match(self):
        assert compare_tmdb_names("One Piece", ["Naruto", "Bleach"]) is False

    def test_empty_input(self):
        assert compare_tmdb_names("", ["test"]) is False
        assert compare_tmdb_names("test", []) is False
        assert compare_tmdb_names(None, ["test"]) is False


class TestGetTmdbChineseTitle:
    def test_cn_simplified(self):
        info = {
            "media_type": MediaType.TV,
            "alternative_titles": {"results": [{"title": "鬼灭之刃", "iso_3166_1": "CN"}]},
        }
        result = get_tmdb_chinese_title(info)
        assert result == "鬼灭之刃"

    def test_tw_traditional_fallback(self):
        info = {
            "media_type": MediaType.TV,
            "alternative_titles": {"results": [{"title": "鬼滅之刃", "iso_3166_1": "TW"}]},
        }
        result = get_tmdb_chinese_title(info)
        assert result == "鬼灭之刃"

    def test_hk_traditional_fallback(self):
        info = {
            "media_type": MediaType.MOVIE,
            "alternative_titles": {"titles": [{"title": "鬼滅之刃", "iso_3166_1": "HK"}]},
        }
        result = get_tmdb_chinese_title(info)
        assert result == "鬼灭之刃"

    def test_no_chinese_title(self):
        info = {
            "media_type": MediaType.MOVIE,
            "alternative_titles": {"titles": []},
            "title": "Kimetsu no Yaiba",
        }
        result = get_tmdb_chinese_title(info)
        assert result == "Kimetsu no Yaiba"

    def test_zh_cn_from_translations(self):
        info = {
            "media_type": MediaType.TV,
            "alternative_titles": {"results": []},
            "name": "Chainsmoker Cat",
            "translations": {
                "translations": [
                    {"iso_639_1": "en", "data": {"name": "Chainsmoker Cat"}},
                    {"iso_639_1": "zh-CN", "data": {"name": "尼古喵喵"}},
                ]
            },
        }
        result = get_tmdb_chinese_title(info)
        assert result == "尼古喵喵"

    def test_zh_tw_from_translations_fallback(self):
        info = {
            "media_type": MediaType.TV,
            "alternative_titles": {"results": []},
            "name": "Chainsmoker Cat",
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-TW", "data": {"name": "尼古喵喵"}},
                ]
            },
        }
        result = get_tmdb_chinese_title(info)
        assert result == "尼古喵喵"

    def test_zh_generic_from_translations(self):
        info = {
            "media_type": MediaType.MOVIE,
            "alternative_titles": {"titles": []},
            "title": "Chainsmoker Cat",
            "translations": {
                "translations": [
                    {"iso_639_1": "zh", "data": {"title": "尼古喵喵"}},
                ]
            },
        }
        result = get_tmdb_chinese_title(info)
        assert result == "尼古喵喵"

    def test_translations_no_chinese(self):
        info = {
            "media_type": MediaType.TV,
            "alternative_titles": {"results": []},
            "name": "Chainsmoker Cat",
            "translations": {"translations": [{"iso_639_1": "en", "data": {"name": "Chainsmoker Cat"}}]},
        }
        result = get_tmdb_chinese_title(info)
        assert result == "Chainsmoker Cat"

    def test_none_info(self):
        assert get_tmdb_chinese_title(None) is None


class TestUpdateTmdbinfoCnTitle:
    def test_fills_cn_title_from_translations(self):
        info = {
            "media_type": MediaType.TV,
            "name": "Chainsmoker Cat",
            "alternative_titles": {"results": []},
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-CN", "data": {"name": "尼古喵喵"}},
                ]
            },
        }
        result = update_tmdbinfo_cn_title(info, "zh")
        assert result["name"] == "尼古喵喵"

    def test_fills_cn_title_with_zh_cn_config(self):
        info = {
            "media_type": MediaType.MOVIE,
            "title": "Chainsmoker Cat",
            "alternative_titles": {"titles": []},
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-CN", "data": {"title": "尼古喵喵"}},
                ]
            },
        }
        result = update_tmdbinfo_cn_title(info, "zh-CN")
        assert result["title"] == "尼古喵喵"

    def test_keep_en_title_when_non_chinese_config(self):
        info = {
            "media_type": MediaType.TV,
            "name": "Chainsmoker Cat",
            "alternative_titles": {"results": []},
            "translations": {
                "translations": [
                    {"iso_639_1": "zh-CN", "data": {"name": "尼古喵喵"}},
                ]
            },
        }
        result = update_tmdbinfo_cn_title(info, "en")
        assert result["name"] == "Chainsmoker Cat"

    def test_keep_cn_title_already_chinese(self):
        info = {"media_type": MediaType.TV, "name": "尼古喵喵", "alternative_titles": {"results": []}}
        result = update_tmdbinfo_cn_title(info, "zh")
        assert result["name"] == "尼古喵喵"
