"""P4 反馈环测试：fan 升格/逐出、miss 周报、手工补边"""

import json
from unittest.mock import MagicMock

from app.indexer.core.miss_collector import weekly_miss_review
from app.media.identity.index import AliasIndex
from app.media.identity.models import ALIAS_FAN, ALIAS_OFFICIAL, AliasEntry


class _MemCache:
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


def _index():
    idx = AliasIndex(alias_adapter=_MemCache(), work_adapter=_MemCache(), graph_adapter=_MemCache())
    return idx


class TestFanPromotion:
    def test_fan_promoted_after_threshold(self):
        idx = _index()
        idx.add_alias("新番X", AliasEntry("tmdb", 100, kind=ALIAS_FAN))
        idx.add_alias("新番X", AliasEntry("tmdb", 100, kind=ALIAS_FAN))
        assert idx.lookup("新番X")[0].kind == "translation"

    def test_record_hit_promotes(self):
        idx = _index()
        idx.add_alias("新番X", AliasEntry("tmdb", 100, kind=ALIAS_FAN))
        idx.record_hit("新番X", "tmdb", 100)
        assert idx.lookup("新番X")[0].kind == "translation"

    def test_fan_single_hit_not_promoted(self):
        idx = _index()
        idx.add_alias("新番X", AliasEntry("tmdb", 100, kind=ALIAS_FAN))
        assert idx.lookup("新番X")[0].kind == ALIAS_FAN

    def test_official_not_demoted(self):
        idx = _index()
        idx.add_alias("正名", AliasEntry("tmdb", 100, kind=ALIAS_OFFICIAL))
        idx.add_alias("正名", AliasEntry("tmdb", 100, kind=ALIAS_FAN))
        assert idx.lookup("正名")[0].kind == ALIAS_OFFICIAL


class TestInvalidateMapping:
    def test_remove_single_mapping(self):
        idx = _index()
        idx.add_alias("攻壳机动队", AliasEntry("tmdb", 255358))
        idx.add_alias("攻壳机动队", AliasEntry("tmdb", 62070))
        assert idx.invalidate_mapping("攻壳机动队", "tmdb", 255358)
        entries = idx.lookup("攻壳机动队")
        assert len(entries) == 1
        assert entries[0].work_id == 62070

    def test_remove_last_mapping_deletes_alias(self):
        idx = _index()
        idx.add_alias("X", AliasEntry("tmdb", 1))
        idx.invalidate_mapping("X", "tmdb", 1)
        assert idx.lookup("X") == []

    def test_remove_nonexistent(self):
        idx = _index()
        idx.add_alias("X", AliasEntry("tmdb", 1))
        assert not idx.invalidate_mapping("X", "tmdb", 999)


class TestWeeklyMissReview:
    def test_review_aggregates_and_rotates(self, tmp_path, monkeypatch):
        path = tmp_path / "identify_misses.jsonl"
        records = [
            {"ts": "2026-07-25 10:00:00", "site": "ACG", "reason": "quick_name_miss", "title": "标题A"},
            {"ts": "2026-07-25 10:01:00", "site": "ACG", "reason": "tmdb_no_match", "title": "标题B"},
            {"ts": "2026-07-25 10:02:00", "site": "Mikan", "reason": "quick_name_miss", "title": "标题A"},
        ]
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")

        import app.indexer.core.miss_collector as mc

        monkeypatch.setattr(mc, "settings", type("S", (), {"data_path": str(tmp_path)})())
        weekly_miss_review()

        assert not path.exists()
        archives = list(tmp_path.glob("identify_misses.jsonl.*"))
        assert len(archives) == 1

    def test_review_no_file(self, tmp_path, monkeypatch):
        import app.indexer.core.miss_collector as mc

        monkeypatch.setattr(mc, "settings", type("S", (), {"data_path": str(tmp_path)})())
        weekly_miss_review()  # 不抛异常


class TestEditionOverrides:
    def test_manual_franchise_loaded(self, tmp_path):
        p = tmp_path / "edition_overrides.yaml"
        p.write_text(
            "edition_overrides:\n"
            "  - franchise: ghost-in-the-shell\n"
            "    name: 攻壳机动队\n"
            "    members:\n"
            "      - {source: tmdb, work_id: 9323}\n"
            "      - {source: tmdb, work_id: 255358}\n",
            encoding="utf-8",
        )
        from app.media.identity.graph import EditionGraph

        graph = EditionGraph.__new__(EditionGraph)
        graph._index = MagicMock()
        graph._bangumi = MagicMock()
        graph._overrides_loaded = False
        import os

        os.environ["NEXUS_EDITION_OVERRIDES"] = str(p)
        try:
            graph._ensure_overrides_loaded()
        finally:
            os.environ.pop("NEXUS_EDITION_OVERRIDES", None)

        graph._index.put_franchise.assert_called_once()
        written = graph._index.put_franchise.call_args[0][0]
        assert written["key"] == "ghost-in-the-shell"
        assert len(written["members"]) == 2
