"""IdentityResolver 测试（ADR-014 P2）"""

from unittest.mock import MagicMock

import pytest

from app.domain.enums import IdentifyStatus
from app.domain.mediatypes import MediaType
from app.media.identity.models import ALIAS_OFFICIAL, AliasEntry, Work
from app.media.identity.resolver import IdentityResolver, extract_edition_markers
from app.media.models import MediaInfo


def _group(names, cn=None, en=None, year=None, mtype=MediaType.TV, seasons=(1,), episodes=(4,), title="title"):
    return {
        "_cache_key": "k1",
        "names": names,
        "cn_name": cn,
        "en_name": en,
        "year": year,
        "type": mtype,
        "seasons": list(seasons),
        "episodes": list(episodes),
        "title": title,
        "site": "T",
        "enclosure": None,
        "size": 1,
        "seeders": 1,
    }


@pytest.fixture
def resolver():
    media = MagicMock()
    media.get_all_names.return_value = []
    r = IdentityResolver.__new__(IdentityResolver)
    r.media = media
    r.index = MagicMock()
    r.index.lookup.return_value = []
    r.graph = MagicMock()
    r.builder = MagicMock()
    return r


class TestExtractEditionMarkers:
    def test_extract(self):
        markers = extract_edition_markers("攻壳机动队 SAC_2045 第二季", "Ghost in the Shell ARISE S01")
        assert "SAC_2045" in markers
        assert "第二季" in markers
        assert any(m.lower() == "arise" for m in markers)

    def test_no_markers(self):
        assert extract_edition_markers("穹庐下的魔女 S01E04") == []


class TestDirectPass:
    def test_all_names_match_direct_hit(self, resolver):
        resolver.media.get_all_names.return_value = ["Jaadugar: A Witch in Mongolia", "天幕のジャードゥーガル"]
        match = MediaInfo(cn_name="穹庐下的魔女", title="穹庐下的魔女", year="2026", type=MediaType.TV, tmdb_id=288971)
        g = _group(["穹庐下的魔女", "Jaadugar: A Witch in Mongolia"], cn="穹庐下的魔女")
        result = resolver.resolve(g, match)
        assert result.status == IdentifyStatus.HIT
        assert result.media_info.tmdb_id == 288971
        assert result.reason == "direct_pass"

    def test_zero_overlap_local_reject(self, resolver):
        resolver.media.get_all_names.return_value = ["Ghost in the Shell"]
        match = MediaInfo(cn_name="攻壳机动队", title="攻壳机动队", year="2026", type=MediaType.TV, tmdb_id=255358)
        g = _group(["Arise Ghost In The Shell Arise"], cn=None, en="Arise Ghost In The Shell Arise", year=None)
        result = resolver.resolve(g, match)
        assert result.status == IdentifyStatus.NOT_FOUND
        assert result.reason == "zero_overlap"


class TestIndexScoring:
    def _work(self, wid, titles, year=2026, aliases=None):
        return Work(source="tmdb", work_id=wid, year=year, official_titles=titles, aliases=aliases or [])

    def test_single_candidate_hit(self, resolver):
        resolver.media.get_all_names.return_value = []
        g = _group(["穹庐下的魔女"], cn="穹庐下的魔女", title="[LoliHouse] 穹庐下的魔女 - 04")
        resolver.index.lookup.side_effect = lambda n: (
            [AliasEntry("tmdb", 288971, kind=ALIAS_OFFICIAL)] if n == "穹庐下的魔女" else []
        )
        resolver.index.get_work.return_value = self._work(288971, ["穹庐下的魔女", "天幕のジャードゥーガル"])

        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.HIT
        assert result.media_info.tmdb_id == 288971
        assert "alias:穹庐下的魔女" in result.evidence

    def test_edition_factor_prefers_marker_work(self, resolver):
        """franchise 名命中多作品时，edition marker 匹配的版本胜出"""
        resolver.media.get_all_names.return_value = []
        g = _group(
            ["攻壳机动队 SAC_2045 第二季"],
            cn="攻壳机动队 SAC_2045 第二季",
            year=None,
            title="[猎户不鸽发布组] 攻壳机动队 SAC_2045 第二季 [12]",
        )
        resolver.index.lookup.side_effect = lambda n: [
            AliasEntry("tmdb", 255358, kind=ALIAS_OFFICIAL),  # 2026 新剧
            AliasEntry("tmdb", 62070, kind=ALIAS_OFFICIAL),  # SAC_2045
        ]
        resolver.index.get_work.side_effect = lambda s, wid: {
            255358: self._work(255358, ["攻壳机动队"], year=2026),
            62070: self._work(62070, ["攻壳机动队：SAC_2045"], year=2020),
        }.get(wid)

        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.HIT
        assert result.media_info.tmdb_id == 62070  # marker 匹配的 SAC_2045 胜出

    def test_below_threshold_falls_to_external(self, resolver):
        resolver.media.get_all_names.return_value = []
        g = _group(["未知剧名"], cn=None, en="未知剧名", year=None)
        resolver.index.lookup.side_effect = lambda n: [AliasEntry("tmdb", 1, kind="fan")]
        resolver.index.get_work.return_value = self._work(1, ["别的剧"], year=1990)
        resolver.media.identify_groups.return_value = {"k1": (IdentifyStatus.NOT_FOUND, MediaInfo(cn_name="未知剧名"))}
        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.NOT_FOUND
        assert result.reason.startswith("external_")


class TestExternalValidation:
    def test_hit_target_with_distinguishing_names_rejected(self, resolver):
        """外部解析命中目标，但组内有未解析名称 → 排除"""
        resolver.media.get_all_names.return_value = ["Ghost in the Shell", "攻殻機動隊"]
        match = MediaInfo(cn_name="攻壳机动队", title="攻壳机动队", year="2026", type=MediaType.TV, tmdb_id=255358)
        g = _group(
            ["攻壳机动队", "Sac 2045 Ghost In The Shell"],
            cn="攻壳机动队",
            en="Sac 2045 Ghost In The Shell",
            year=None,
        )
        resolver.index.lookup.side_effect = lambda n: []
        resolver.media.identify_groups.return_value = {
            "k1": (IdentifyStatus.HIT, MediaInfo(cn_name="攻壳机动队", tmdb_id=255358))
        }
        result = resolver.resolve(g, match)
        assert result.status == IdentifyStatus.NOT_FOUND
        assert result.reason == "distinguishing_names"

    def test_external_hit_writes_fan_alias(self, resolver):
        resolver.media.get_all_names.return_value = []
        g = _group(["新番中文名"], cn="新番中文名")
        resolver.index.lookup.side_effect = lambda n: []
        resolver.media.identify_groups.return_value = {
            "k1": (IdentifyStatus.HIT, MediaInfo(cn_name="新番中文名", tmdb_id=999))
        }
        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.HIT
        # fan 别名回写
        args = resolver.index.add_alias.call_args[0]
        assert args[0] == "新番中文名"
        assert args[1].kind == "fan"
        assert args[1].work_id == 999

    def test_external_hit_learns_work_metadata(self, resolver):
        """外部解析命中后回写最小 Work 元数据（冷→热闭环：下次本地可评分命中）"""
        resolver.media.get_all_names.return_value = []
        g = _group(["新番中文名"], cn="新番中文名")
        resolver.index.lookup.side_effect = lambda n: []
        resolver.index.get_work.return_value = None  # Work 元数据未索引
        resolver.media.identify_groups.return_value = {
            "k1": (
                IdentifyStatus.HIT,
                MediaInfo(
                    cn_name="新番中文名",
                    title="新番中文名",
                    original_title="Shin Bangumi",
                    year="2026",
                    type=MediaType.TV,
                    tmdb_id=999,
                ),
            )
        }
        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.HIT
        work = resolver.index.put_work.call_args[0][0]
        assert work.work_id == 999
        assert work.official_titles == ["新番中文名", "Shin Bangumi"]
        assert work.aliases[0].kind == "fan"

    def test_external_hit_skips_work_when_already_indexed(self, resolver):
        """Work 已索引时不再重复回写（避免覆盖已构建的完整元数据）"""
        resolver.media.get_all_names.return_value = []
        g = _group(["新番中文名"], cn="新番中文名")
        resolver.index.lookup.side_effect = lambda n: []
        resolver.index.get_work.return_value = Work(
            source="tmdb", work_id=999, official_titles=["完整版名称"], aliases=[]
        )
        resolver.media.identify_groups.return_value = {
            "k1": (IdentifyStatus.HIT, MediaInfo(cn_name="新番中文名", tmdb_id=999))
        }
        result = resolver.resolve(g, None)
        assert result.status == IdentifyStatus.HIT
        resolver.index.put_work.assert_not_called()


class TestEditionGraph:
    def test_find_edition(self):
        from app.media.identity.graph import EditionGraph

        index = MagicMock()
        index.get_franchise.return_value = {
            "key": "ghostintheshell",
            "name": "攻壳机动队",
            "members": [["tmdb", 255358], ["tmdb", 62070]],
        }
        index.get_work.side_effect = lambda s, wid: (
            Work(source="tmdb", work_id=255358, official_titles=["攻壳机动队"])
            if wid == 255358
            else Work(source="tmdb", work_id=62070, official_titles=["攻壳机动队：SAC_2045"])
        )
        graph = EditionGraph.__new__(EditionGraph)
        graph._index = index
        graph._bangumi = MagicMock()
        graph._overrides_loaded = True

        assert graph.find_edition("ghostintheshell", ["SAC_2045"]) == ("tmdb", 62070)
        assert graph.find_edition("ghostintheshell", ["不存在的版本"]) is None
        assert graph.find_edition("ghostintheshell", []) is None
