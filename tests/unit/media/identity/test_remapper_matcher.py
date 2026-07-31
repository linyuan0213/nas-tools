"""EpisodeRemapper / TargetMatcher 测试（ADR-014 P3）"""

from typing import Any
from unittest.mock import MagicMock

from app.media.identity.matcher import TargetMatcher
from app.media.identity.models import Work
from app.media.identity.remapper import EpisodeRemapper
from app.media.models import MediaInfo


class TestEpisodeRemapper:
    def _remapper(self, season_map=None):
        r = EpisodeRemapper.__new__(EpisodeRemapper)
        r._mapper: Any = MagicMock()  # type: ignore[assignment]
        r._season_map = season_map or {}
        r._overrides = {"numbering_overrides": [], "edition_overrides": []}
        return r

    def test_numbering_override(self):
        """发布组季号 → 规范季号（SAC_2045 被发布组计为 S3/S4）"""
        r = self._remapper({97699: {3: 1, 4: 2}})
        assert r.remap(97699, 4, 12) == (2, 12)
        assert r.remap(97699, 3, 1) == (1, 1)

    def test_override_miss_falls_to_mapper(self):
        r = self._remapper({97699: {4: 2}})
        r._mapper.map_auto.return_value = (1, 46)  # type: ignore[union-attr]
        assert r.remap(97699, 2, 46) == (1, 46)
        r._mapper.map_auto.assert_called_once_with(97699, 2, 46, None)  # type: ignore[union-attr]

    def test_no_tmdb_id(self):
        r = self._remapper({97699: {4: 2}})
        assert r.remap(0, 4, 12) is None

    def test_remap_batch_mixed(self):
        r = self._remapper({97699: {4: 2}})
        r._mapper.map_batch.return_value = [(1, 46)]  # type: ignore[union-attr]
        items = [
            {"tmdb_id": 97699, "season": 4, "episode": 12},
            {"tmdb_id": 111, "season": 2, "episode": 46},
        ]
        results = r.remap_batch(items)
        assert results[0] == (2, 12)  # override
        assert results[1] == (1, 46)  # mapper

    def test_expand_pack(self):
        r = self._remapper()
        r._mapper._tmdb.get_tmdb_info.return_value = {  # type: ignore[union-attr]
            "seasons": [
                {"season_number": 1, "episode_count": 2},
                {"season_number": 2, "episode_count": 3},
            ]
        }
        assert r.expand_pack(288971, [1, 2]) == [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3)]
        assert r.expand_pack(288971, [3]) is None

    def test_load_overrides_file(self, tmp_path):
        p = tmp_path / "ov.yaml"
        p.write_text("numbering_overrides:\n  - tmdb_id: 97699\n    season_map: {4: 2}\n", encoding="utf-8")
        r = EpisodeRemapper(overrides_path=p)
        assert r.remap(97699, 4, 12) == (2, 12)


class TestTargetMatcher:
    def _matcher(self, works=None):
        index = MagicMock()
        index.get_work.side_effect = lambda s, wid: (works or {}).get(wid)
        return TargetMatcher(graph=MagicMock(), index=index)

    def test_id_match(self):
        m = self._matcher()
        result = m.match(
            MediaInfo(cn_name="穹庐下的魔女", tmdb_id=288971),
            MediaInfo(cn_name="穹庐下的魔女", tmdb_id=288971),
        )
        assert result.matched and result.reason == "id_match"

    def test_mismatch_no_franchise(self):
        m = self._matcher()
        result = m.match(
            MediaInfo(cn_name="攻壳机动队：SAC_2045", tmdb_id=62070),
            MediaInfo(cn_name="攻壳机动队", tmdb_id=255358),
        )
        assert not result.matched
        assert "非同一作品" in result.reason

    def test_mismatch_same_franchise_explainable(self):
        """同 franchise 不同 edition → 可解释拒绝"""
        works = {
            62070: Work(source="tmdb", work_id=62070, franchise="ghostintheshell", official_titles=["SAC_2045"]),
            255358: Work(source="tmdb", work_id=255358, franchise="ghostintheshell", official_titles=["攻壳机动队"]),
        }
        m = self._matcher(works)
        result = m.match(
            MediaInfo(cn_name="攻壳机动队：SAC_2045", tmdb_id=62070),
            MediaInfo(cn_name="攻壳机动队", tmdb_id=255358),
        )
        assert not result.matched
        assert "同系列不同版本" in result.reason

    def test_no_identity(self):
        m = self._matcher()
        result = m.match(MediaInfo(cn_name="未知"), MediaInfo(tmdb_id=1))
        assert not result.matched
        assert result.reason == "no_identity"

    def test_no_target(self):
        m = self._matcher()
        result = m.match(MediaInfo(tmdb_id=1), MediaInfo())  # no_target via no tmdb_id
        assert result.matched
