"""身份元数据层测试（ADR-014 P1）"""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.mediatypes import MediaType
from app.media.identity.builder import IdentityIndexBuilder
from app.media.identity.index import AliasIndex
from app.media.identity.models import (
    ALIAS_FAN,
    ALIAS_OFFICIAL,
    ALIAS_ROMANIZATION,
    ALIAS_TRANSLATION,
    Alias,
    AliasEntry,
    Work,
    normalize_text,
)


class TestModels:
    def test_work_roundtrip(self):
        work = Work(
            source="tmdb",
            work_id=288971,
            media_type="anime",
            year=2026,
            official_titles=["穹庐下的魔女", "天幕のジャードゥーガル"],
            aliases=[Alias(text="Tenmaku no Jaadugar", kind=ALIAS_ROMANIZATION, source="tmdb:translations")],
        )
        restored = Work.from_dict(work.to_dict())
        assert restored.work_id == 288971
        assert restored.aliases[0].text == "Tenmaku no Jaadugar"
        assert restored.aliases[0].kind == ALIAS_ROMANIZATION

    def test_all_name_strings_dedup(self):
        work = Work(
            source="tmdb",
            work_id=1,
            official_titles=["A", "B"],
            aliases=[Alias(text="B"), Alias(text="C")],
        )
        assert work.all_name_strings() == ["A", "B", "C"]

    def test_normalize_text(self):
        assert normalize_text("Jaadugar: A Witch in Mongolia") == normalize_text("Jaadugar A Witch In Mongolia")


class TestAliasIndex:
    @pytest.fixture
    def index(self):
        idx = AliasIndex(alias_adapter=_MemCache(), work_adapter=_MemCache(), graph_adapter=_MemCache())
        return idx

    def test_lookup_empty(self, index):
        assert index.lookup("") == []
        assert index.lookup("不存在的名字") == []

    def test_add_and_lookup(self, index):
        index.add_alias("穹庐下的魔女", AliasEntry("tmdb", 288971, kind=ALIAS_OFFICIAL))
        entries = index.lookup("穹庐下的魔女")
        assert len(entries) == 1
        assert entries[0].work_id == 288971

    def test_add_alias_multi_works(self, index):
        index.add_alias("攻壳机动队", AliasEntry("tmdb", 255358))
        index.add_alias("攻壳机动队", AliasEntry("tmdb", 801))
        entries = index.lookup("攻壳机动队")
        assert {e.work_id for e in entries} == {255358, 801}

    def test_fan_not_override_official(self, index):
        index.add_alias("X剧", AliasEntry("tmdb", 1, kind=ALIAS_OFFICIAL))
        index.add_alias("X剧", AliasEntry("tmdb", 1, kind=ALIAS_FAN))
        assert index.lookup("X剧")[0].kind == ALIAS_OFFICIAL

    def test_invalidate(self, index):
        index.add_alias("X剧", AliasEntry("tmdb", 1))
        index.invalidate("X剧")
        assert index.lookup("X剧") == []

    def test_put_work_populates_aliases(self, index):
        work = Work(
            source="tmdb",
            work_id=288971,
            official_titles=["穹庐下的魔女"],
            aliases=[Alias(text="Tenmaku no Jaadugar", kind=ALIAS_ROMANIZATION)],
        )
        index.put_work(work)
        assert index.lookup("穹庐下的魔女")[0].work_id == 288971
        assert index.lookup("Tenmaku no Jaadugar")[0].work_id == 288971
        assert index.get_work_names("tmdb", 288971) == ["穹庐下的魔女", "Tenmaku no Jaadugar"]


class _MemCache:
    """测试用内存缓存（模拟 tiered 适配器接口）"""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl=None):
        self._data[key] = value
        return True

    def delete(self, key):
        self._data.pop(key, None)
        return True


class TestBuilder:
    def _builder(self):
        b = IdentityIndexBuilder.__new__(IdentityIndexBuilder)
        b._index = MagicMock()
        b._bangumi = MagicMock()
        b._tmdb_detail = MagicMock()
        return b

    def test_build_tmdb_work_alias_kinds(self):
        info = {
            "name": "穹庐下的魔女",
            "original_name": "天幕のジャードゥーガル",
            "original_language": "ja",
            "first_air_date": "2026-07-04",
            "alternative_titles": {"results": [{"title": "Jaadugar: A Witch in Mongolia"}, {"title": "天幕的賈杜加"}]},
            "translations": {
                "translations": [
                    {"iso_639_1": "en", "data": {"name": "A Witch's Life in Mongol"}},
                    {"iso_639_1": "zh", "data": {"name": "穹庐下的魔女"}},
                ]
            },
        }
        work = IdentityIndexBuilder._build_tmdb_work(288971, MediaType.TV, info)
        assert work.year == 2026
        assert work.official_titles == ["穹庐下的魔女", "天幕のジャードゥーガル"]
        kinds = {a.text: a.kind for a in work.aliases}
        # 日产作品的拉丁字母别名 → romanization
        assert kinds["Jaadugar: A Witch in Mongolia"] == ALIAS_ROMANIZATION
        assert kinds["A Witch's Life in Mongol"] == ALIAS_ROMANIZATION
        assert kinds["天幕的賈杜加"] == ALIAS_TRANSLATION

    def test_ensure_tmdb_work_cached(self):
        b = self._builder()
        b._index.get_work.return_value = Work(source="tmdb", work_id=288971, official_titles=["穹庐下的魔女"])  # type: ignore[union-attr]
        work = b.ensure_tmdb_work(288971, MediaType.TV)
        assert work.work_id == 288971  # type: ignore[union-attr]
        b._tmdb_detail.get_detail.assert_not_called()  # type: ignore[union-attr]

    def test_ensure_tmdb_work_fetch_and_store(self):
        b = self._builder()
        b._index.get_work.return_value = None  # type: ignore[union-attr]
        b._tmdb_detail.get_detail.return_value = {  # type: ignore[union-attr]
            "name": "穹庐下的魔女",
            "original_name": "天幕のジャードゥーガル",
            "original_language": "ja",
            "first_air_date": "2026-07-04",
        }
        work = b.ensure_tmdb_work(288971, MediaType.TV)
        assert work.work_id == 288971  # type: ignore[union-attr]
        b._index.put_work.assert_called_once()  # type: ignore[union-attr]

    def test_ensure_tmdb_work_fetch_failure(self):
        b = self._builder()
        b._index.get_work.return_value = None  # type: ignore[union-attr]
        b._tmdb_detail.get_detail.side_effect = RuntimeError("boom")  # type: ignore[union-attr]
        assert b.ensure_tmdb_work(288971, MediaType.TV) is None

    def test_get_work_names_tmdb(self):
        b = self._builder()
        b._index.get_work.return_value = None  # type: ignore[union-attr]
        b._tmdb_detail.get_detail.return_value = {  # type: ignore[union-attr]
            "name": "穹庐下的魔女",
            "original_language": "ja",
            "first_air_date": "2026-07-04",
        }
        names = b.get_work_names("tmdb", 288971, MediaType.TV)
        assert names == ["穹庐下的魔女"]


class TestBangumiRelations:
    def test_relations_returns_list(self):
        from app.media.external.bangumi import Bangumi

        with patch.object(Bangumi, "_Bangumi__invoke", return_value=[{"id": 1, "relation": "续集"}]):
            assert Bangumi().relations(288971) == [{"id": 1, "relation": "续集"}]

    def test_relations_failure_returns_empty(self):
        from app.media.external.bangumi import Bangumi

        with patch.object(Bangumi, "_Bangumi__invoke", side_effect=RuntimeError("boom")):
            assert Bangumi().relations(288971) == []


class TestGetAllNamesSwitch:
    def test_flag_off_uses_legacy(self):
        from app.media.service import MediaService

        svc = MediaService.__new__(MediaService)
        svc._lookup = MagicMock()
        svc._lookup.all_names.return_value = ["A", "B"]
        with patch("app.media.service.settings") as mock_settings:
            mock_settings.get.return_value = {"identity_index": False}
            assert svc.get_all_names(1, MediaType.TV) == ["A", "B"]
        svc._lookup.all_names.assert_called_once()

    def test_flag_on_uses_index(self):
        from app.media.service import MediaService

        svc = MediaService.__new__(MediaService)
        svc._lookup = MagicMock()
        with (
            patch("app.media.service.settings") as mock_settings,
            patch("app.media.service.get_identity_builder") as mock_builder,
        ):
            mock_settings.get.return_value = {"identity_index": True}
            mock_builder.return_value.get_work_names.return_value = ["X", "Y"]
            assert svc.get_all_names(1, MediaType.TV) == ["X", "Y"]
        svc._lookup.all_names.assert_not_called()

    def test_flag_on_fallback_to_legacy(self):
        from app.media.service import MediaService

        svc = MediaService.__new__(MediaService)
        svc._lookup = MagicMock()
        svc._lookup.all_names.return_value = ["legacy"]
        with (
            patch("app.media.service.settings") as mock_settings,
            patch("app.media.service.get_identity_builder") as mock_builder,
        ):
            mock_settings.get.return_value = {"identity_index": True}
            mock_builder.return_value.get_work_names.side_effect = RuntimeError("boom")
            assert svc.get_all_names(1, MediaType.TV) == ["legacy"]
