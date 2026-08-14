"""BatchIdentifier 分组识别测试"""

import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.enums import IdentifyStatus
from app.domain.mediatypes import MediaType
from app.indexer.core.batch_identifier import BatchIdentifier
from app.indexer.core.models import SearchCandidate
from app.infrastructure.cache_system import get_cache_manager
from app.infrastructure.http.exceptions import HttpRateLimitError
from app.media.lookup.base import LookupResult
from app.media.models import MediaInfo
from app.media.service import MediaService

_cache_seq = itertools.count()


def _meta(cn=None, en=None, year: str | None = "2026", mtype=MediaType.TV, seasons=(1,), episodes=(4,)):
    return SimpleNamespace(
        cn_name=cn,
        en_name=en,
        year=year,
        type=mtype,
        get_name=lambda: cn or en,
        get_season_list=lambda: list(seasons),
        get_episode_list=lambda: list(episodes),
    )


def _cand(title, meta):
    return SearchCandidate(item={"title": title, "site": "Test", "size": 100, "seeders": 5}, meta_info=meta)


@pytest.fixture
def identifier():
    svc = MagicMock()
    svc.get_all_names.return_value = []
    ident = BatchIdentifier(media_service=svc, progress=MagicMock())
    # 每个测试独立的内存缓存，避免共享缓存导致用例间污染
    ident._media_ident_cache = get_cache_manager().get_or_create(
        f"media_ident_test_{next(_cache_seq)}", "memory", maxsize=100, ttl=3600
    )
    return ident


class TestGroupAggregation:
    """P0: 组内名称候选聚合，中文优先"""

    def test_same_episode_merges_into_one_group_cn_first(self, identifier):
        # 生产场景中同集所有候选有相同的 en_name（或都无）
        cands = [
            _cand(
                "Jaadugar A Witch in Mongolia S01E04 1080p",
                _meta(cn="穹庐下的魔女", en="Tenmaku no Jaadugar"),
            ),
            _cand("[LoliHouse] 穹庐下的魔女 - 04", _meta(cn="穹庐下的魔女", en="Tenmaku no Jaadugar")),
        ]
        identifier.media.identify_groups.return_value = {}

        identifier.identify(cands)

        groups = identifier.media.identify_groups.call_args[0][0]
        assert len(groups) == 1
        assert groups[0]["names"][0] == "穹庐下的魔女"
        assert set(groups[0]["names"]) == {"穹庐下的魔女", "Tenmaku no Jaadugar"}

    def test_invalid_names_filtered(self, identifier):
        cands = [_cand("xxx", _meta(cn=None, en="1080p"))]
        identifier.media.identify_groups.return_value = {}

        identifier.identify(cands)

        groups = identifier.media.identify_groups.call_args[0][0]
        assert groups[0]["names"] == []


class TestDirectPass:
    """P2: match_media 先验直通"""

    def _match_media(self, year="2026"):
        return MediaInfo(
            cn_name="穹庐下的魔女",
            title="穹庐下的魔女",
            original_title="天幕のジャードゥーガル",
            year=year,
            type=MediaType.TV,
            tmdb_id=288971,
            tmdb_info={"id": 288971, "title": "穹庐下的魔女"},
        )

    def test_direct_pass_caches_without_tmdb(self, identifier):
        cands = [_cand("Jaadugar A Witch in Mongolia S01E04 2026", _meta(cn="穹庐下的魔女"))]

        identifier.identify(cands, match_media=self._match_media())

        identifier.media.identify_groups.assert_not_called()
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        cached = identifier._media_ident_cache.get(key)
        assert cached is not None
        assert cached.tmdb_id == 288971

    def test_tv_year_mismatch_not_rejected(self, identifier):
        """剧集跨年份（S2 播映年晚于首播年）→ 名称匹配仍直通，零 API"""
        cands = [_cand("Jaadugar A Witch in Mongolia S01E04 2026", _meta(cn="穹庐下的魔女", year="2026"))]

        identifier.identify(cands, match_media=self._match_media(year="2025"))

        identifier.media.identify_groups.assert_not_called()
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        cached = identifier._media_ident_cache.get(key)
        assert cached is not None
        assert cached.tmdb_id == 288971

    def test_movie_year_mismatch_locally_rejected(self, identifier):
        """电影年份冲突 → 本地排除，零 API（同名不同年的电影是不同作品）"""
        cands = [
            _cand(
                "Ghostbusters 2016 1080p",
                _meta(cn="超能敢死队", en="Ghostbusters", year="2016", mtype=MediaType.MOVIE),
            )
        ]
        movie_match = MediaInfo(
            cn_name="超能敢死队",
            title="捉鬼敢死队",
            en_name="Ghostbusters",
            year="1984",
            type=MediaType.MOVIE,
            tmdb_id=123,
        )

        identifier.identify(cands, match_media=movie_match)

        identifier.media.identify_groups.assert_not_called()
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        cached = identifier._media_ident_cache.get(key)
        assert cached is not None
        assert not cached.tmdb_id

    def test_distinguishing_en_name_goes_to_consensus(self, identifier):
        """攻壳机动队(2026)：中文通称匹配、英文子系列名不匹配 → 交 TMDB 共识仲裁"""
        match = MediaInfo(
            cn_name="攻壳机动队",
            title="攻壳机动队",
            original_title="攻殻機動隊",
            year="2026",
            type=MediaType.TV,
            tmdb_id=999999,
            tmdb_info={"id": 999999},
        )
        identifier.media.get_all_names.return_value = ["Ghost in the Shell", "攻殻機動隊", "The Ghost in the Shell"]
        cands = [
            _cand(
                "Ghost in the Shell Stand Alone Complex S04 1080p NF WEB-DL",
                _meta(cn="攻壳机动队", en="Ghost in the Shell Stand Alone Complex", year=None),
            )
        ]
        group_key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        identifier.media.identify_groups.return_value = {
            group_key: (IdentifyStatus.HIT, MediaInfo(cn_name="攻壳机动队 S.A.C.", tmdb_id=801))
        }

        identifier.identify(cands, match_media=match)

        # 部分重叠 = 存在区分信息 → 走 TMDB 共识
        identifier.media.identify_groups.assert_called_once()
        # 结果应从缓存读取，tmdb 不是目标
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        assert identifier._media_ident_cache.get(key).tmdb_id == 801

    def test_all_names_match_with_enriched_aliases(self, identifier):
        """目标别名扩充后，罗马字/英文名也参与全名共识，直通仍高效"""
        identifier.media.get_all_names.return_value = [
            "Jaadugar: A Witch in Mongolia",
            "Tenmaku no Jaadugar",
            "天幕のジャードゥーガル",
        ]
        cands = [
            _cand(
                "Jaadugar A Witch in Mongolia S01E04 2026",
                _meta(cn="穹庐下的魔女", en="Jaadugar: A Witch in Mongolia"),
            )
        ]

        identifier.identify(cands, match_media=self._match_media())

        identifier.media.identify_groups.assert_not_called()
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        assert identifier._media_ident_cache.get(key).tmdb_id == 288971

    def test_zero_overlap_locally_rejected(self, identifier):
        """名称与目标零重叠 → 本地排除，不走 TMDB（750 条泛词场景的性能关键）"""
        match = MediaInfo(
            cn_name="攻壳机动队",
            title="攻壳机动队",
            year="2026",
            type=MediaType.TV,
            tmdb_id=999999,
            tmdb_info={"id": 999999},
        )
        identifier.media.get_all_names.return_value = ["Ghost in the Shell", "攻殻機動隊"]
        cands = [
            _cand(
                "Arise Ghost in the Shell Arise S01E01",
                _meta(cn=None, en="Arise Ghost In The Shell Arise", year=None),
            )
        ]

        identifier.identify(cands, match_media=match)

        identifier.media.identify_groups.assert_not_called()
        key = BatchIdentifier.build_cache_key(cands[0].meta_info)
        cached = identifier._media_ident_cache.get(key)
        assert cached is not None
        assert not cached.tmdb_id


class TestStatusCaching:
    """P1: HIT / NOT_FOUND / ERROR 三级缓存语义"""

    def test_hit_and_not_found_cached_error_not(self, identifier):
        metas = [
            ("hit", _meta(cn="命中剧", episodes=(1,))),
            ("nf", _meta(cn="无结果剧", episodes=(2,))),
            ("err", _meta(cn="异常剧", episodes=(3,))),
        ]
        cands = [_cand(f"title_{k}", m) for k, m in metas]
        keys = [BatchIdentifier.build_cache_key(m) for _, m in metas]
        identifier.media.identify_groups.return_value = {
            keys[0]: (IdentifyStatus.HIT, MediaInfo(cn_name="命中剧", tmdb_id=1)),
            keys[1]: (IdentifyStatus.NOT_FOUND, MediaInfo(cn_name="无结果剧")),
            keys[2]: (IdentifyStatus.ERROR, MediaInfo(cn_name="异常剧")),
        }

        identifier.identify(cands)

        assert identifier._media_ident_cache.get(keys[0]) is not None
        assert identifier._media_ident_cache.get(keys[1]) is not None
        assert identifier._media_ident_cache.get(keys[2]) is None


class TestIdentifyGroups:
    """MediaService.identify_groups 名称尝试与状态"""

    def _service(self, lookup):
        svc = MediaService.__new__(MediaService)
        svc._lookup = lookup
        svc._episode_mapping_enabled = False
        return svc

    def _group(self, names):
        return {
            "_cache_key": "v2_test_S1_E1",
            "names": names,
            "cn_name": "穹庐下的魔女",
            "en_name": "Jaadugar",
            "year": "2026",
            "type": MediaType.TV,
            "seasons": [1],
            "episodes": [1],
            "title": "org title",
            "site": "Test",
            "enclosure": None,
            "size": 1,
            "seeders": 1,
        }

    def test_cn_name_hit_with_consensus(self):
        lookup = MagicMock()
        hit = LookupResult(tmdb_id=288971, title="穹庐下的魔女", media_type=MediaType.TV)
        lookup.lookup.return_value = hit
        svc = self._service(lookup)

        result = svc.identify_groups([self._group(["穹庐下的魔女", "Jaadugar"])])

        status, info = result["v2_test_S1_E1"]
        assert status == IdentifyStatus.HIT
        assert info.tmdb_id == 288971
        # 共识机制：所有名称都会被查询
        assert lookup.lookup.call_count == 2
        first = lookup.lookup.call_args_list[0][0][0]
        assert first.title_cn == "穹庐下的魔女"

    def test_conflict_prefers_most_specific_name(self):
        """攻壳机动队案例：中文通称命中 2026 新剧，英文子系列名命中 SAC，
        冲突时采信最具体（最长）名称"""
        lookup = MagicMock()
        lookup.lookup.side_effect = [
            LookupResult(tmdb_id=999999, title="攻壳机动队", media_type=MediaType.TV),  # cn: 2026 新剧
            LookupResult(tmdb_id=801, title="攻壳机动队 S.A.C.", media_type=MediaType.TV),  # en: SAC
        ]
        svc = self._service(lookup)

        group = self._group(["攻壳机动队", "Ghost in the Shell Stand Alone Complex"])
        result = svc.identify_groups([group])

        status, info = result["v2_test_S1_E1"]
        assert status == IdentifyStatus.HIT
        assert info.tmdb_id == 801

    def test_fallback_to_en_name(self):
        lookup = MagicMock()
        lookup.lookup.side_effect = [None, LookupResult(tmdb_id=288971, media_type=MediaType.TV)]
        svc = self._service(lookup)

        result = svc.identify_groups([self._group(["穹庐下的魔女", "Jaadugar"])])

        status, _ = result["v2_test_S1_E1"]
        assert status == IdentifyStatus.HIT
        assert lookup.lookup.call_count == 2
        second = lookup.lookup.call_args[0][0]
        assert second.title_en == "Jaadugar"

    def test_not_found_when_all_names_miss(self):
        lookup = MagicMock()
        lookup.lookup.return_value = None
        svc = self._service(lookup)

        result = svc.identify_groups([self._group(["穹庐下的魔女", "Jaadugar"])])

        status, info = result["v2_test_S1_E1"]
        assert status == IdentifyStatus.NOT_FOUND
        assert not info.tmdb_id

    def test_rate_limit_returns_error(self):
        lookup = MagicMock()
        lookup.lookup.side_effect = HttpRateLimitError("Rate limit exceeded: tmdb:api")
        svc = self._service(lookup)

        result = svc.identify_groups([self._group(["穹庐下的魔女", "Jaadugar"])])

        status, _ = result["v2_test_S1_E1"]
        assert status == IdentifyStatus.ERROR
        assert lookup.lookup.call_count == 1
