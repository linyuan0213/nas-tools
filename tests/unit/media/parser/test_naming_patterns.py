"""命名模式库引擎测试"""

import time

import pytest

from app.media.parser.naming_patterns import NamingPatternLibrary, apply_hit_to_info


@pytest.fixture
def lib():
    return NamingPatternLibrary()


class TestSeedRules:
    """种子规则与真实样本（穹庐下的魔女事件）"""

    @pytest.mark.parametrize(
        ("title", "cn", "en", "episode"),
        [
            (
                "[北宇治字幕组] 穹庐下的魔女 / 穹廬下的魔女 / Tenmaku no Jaadugar [01][WebRip][HEVC_AAC][简繁日内封]",
                "穹庐下的魔女",
                "Tenmaku no Jaadugar",
                None,
            ),
            (
                "[绿茶字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [04][WebRip][1080p][繁日内嵌]",
                "穹庐下的魔女",
                "Tenmaku no Jaadugar",
                None,
            ),
            (
                "[黒ネズミたち] 穹庐下的魔女 / Tenmaku no Jaadugar - 04 (ABEMA 1920x1080 AVC AAC MKV)",
                "穹庐下的魔女",
                "Tenmaku no Jaadugar",
                None,
            ),
            (
                "[ANi] Tenmaku no Jādūgar /  穹庐下的魔女 - 04 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
                "穹庐下的魔女",
                "Tenmaku no Jādūgar",
                "04",
            ),
            ("[Up to 21°C] 學姊是男孩 - 03 (Baha 1920x1080 AVC AAC MP4) [4D0F1DB2]", "學姊是男孩", None, "03"),
        ],
    )
    def test_samples(self, lib, title, cn, en, episode):
        hit = lib.apply(title)
        assert hit is not None, f"未命中: {title}"
        assert hit.get("cn_name") == cn
        if en:
            assert hit.get("en_name") == en
        if episode:
            assert hit.get("episode") == episode

    def test_no_match_returns_none(self, lib):
        assert lib.apply("Jaadugar A Witch in Mongolia S01E04 2026 1080p Baha WEB-DL") is None

    def test_empty_title(self, lib):
        assert lib.apply("") is None
        assert lib.apply(None) is None


class TestEngineBehavior:
    def _write_rules(self, tmp_path, body):
        p = tmp_path / "rules.yaml"
        p.write_text(body, encoding="utf-8")
        return p

    def test_invalid_regex_skipped(self, tmp_path):
        p = self._write_rules(
            tmp_path,
            "rules:\n  - name: bad\n    pattern: '([未闭合'\n  - name: good\n    pattern: '(?P<cn_name>[一-鿿]+)'\n",
        )
        lib = NamingPatternLibrary(path=p)
        assert [r.name for r in lib.rules] == ["good"]

    def test_missing_fields_skipped(self, tmp_path):
        p = self._write_rules(tmp_path, "rules:\n  - name: nope\ndescription: 无 pattern\n")
        lib = NamingPatternLibrary(path=p)
        assert lib.rules == []

    def test_first_match_wins(self, tmp_path):
        p = self._write_rules(
            tmp_path,
            "rules:\n"
            "  - name: first\n    pattern: '(?P<cn_name>穹庐下的魔女)'\n"
            "  - name: second\n    pattern: '(?P<en_name>魔女)'\n",
        )
        lib = NamingPatternLibrary(path=p)
        hit = lib.apply("[LoliHouse] 穹庐下的魔女 - 01")
        assert hit is not None
        assert hit["rule"] == "first"

    def test_precondition_match_filter(self, tmp_path):
        p = self._write_rules(
            tmp_path,
            "rules:\n  - name: ani-only\n    match: '^\\[ANi\\]'\n    pattern: '(?P<en_name>[A-Za-z ]+)'\n",
        )
        lib = NamingPatternLibrary(path=p)
        assert lib.apply("[Other] Some Title") is None
        assert lib.apply("[ANi] Some Title - 01") is not None

    def test_hot_reload(self, tmp_path):
        p = self._write_rules(tmp_path, "rules:\n  - name: a\n    pattern: '(?P<cn_name>旧规则)'")
        lib = NamingPatternLibrary(path=p)
        assert lib.apply("旧规则标题") is not None
        assert lib.apply("新规则标题") is None
        time.sleep(0.01)
        p.write_text("rules:\n  - name: b\n    pattern: '(?P<cn_name>新规则)'", encoding="utf-8")
        import os

        os.utime(p, (time.time() + 10, time.time() + 10))
        lib._last_check = 0
        assert lib.apply("新规则标题") is not None


class TestApplyHitToInfo:
    def test_numeric_fields(self):
        from app.media.models import MediaInfo

        info = MediaInfo()
        apply_hit_to_info(info, {"season": "01", "episode": "04", "year": "2026"})
        assert info.begin_season == 1
        assert info.begin_episode == 4
        assert info.year == "2026"

    def test_year_not_overwritten(self):
        from app.media.models import MediaInfo

        info = MediaInfo(year="2025")
        apply_hit_to_info(info, {"year": "2026"})
        assert info.year == "2025"

    def test_invalid_numbers_ignored(self):
        from app.media.models import MediaInfo

        info = MediaInfo()
        apply_hit_to_info(info, {"season": "abc", "episode": None})
        assert info.begin_season is None
        assert info.begin_episode is None
