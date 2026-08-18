"""回归测试：自定义识别词（屏蔽 / 替换 / 集偏移）在转移识别路径生效"""

import pytest

from app.domain.word_processor import set_words_info
from app.media.parser.regex import RegexParser
from app.media.service import MediaService

_IGNORE = {
    "TYPE": 1,
    "REGEX": 1,
    "ENABLED": 1,
    "REPLACED": r"\[EZTVx?\.to\]",
    "REPLACE": "",
    "FRONT": "",
    "BACK": "",
    "OFFSET": "",
}

_REPLACE = {
    "TYPE": 2,
    "REGEX": 1,
    "ENABLED": 1,
    "REPLACED": r"\[EZTVx?\.to\]",
    "REPLACE": "",
    "FRONT": "",
    "BACK": "",
    "OFFSET": "",
}

_TITLE = "The.Boys.S04E08.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv"


def _word(**overrides):
    fields = dict(_IGNORE)
    fields.update(overrides)
    return type("CustomWord", (object,), fields)()


@pytest.fixture
def no_words():
    set_words_info([])
    yield
    set_words_info([])


@pytest.fixture
def ignore_word():
    set_words_info([_word()])
    yield
    set_words_info([])


def test_transfer_path_applies_ignored_word(no_words, ignore_word):
    """转移路径（_apply_words + RegexParser）应套用屏蔽词，剥离站点标记."""
    rev, _sub = MediaService._apply_words(_TITLE)
    parsed = RegexParser().parse(rev)
    assert parsed is not None
    assert parsed.title_en == "The Boys"
    assert parsed.season == 4
    assert parsed.episode == 8


def test_without_words_builtin_marker_stripped(no_words):
    """无自定义识别词时，内置站点标记剥离仍生效，[EZTVx.to] 不抢占剧名."""
    rev, _sub = MediaService._apply_words(_TITLE)
    parsed = RegexParser().parse(rev)
    assert parsed is not None
    assert parsed.title_en == "The Boys"


def test_replace_word_applied(no_words):
    """替换词同样在转移路径生效."""
    set_words_info([_word(TYPE=2, REPLACED=r"\[EZTVx?\.to\]", REPLACE="")])
    rev, _sub = MediaService._apply_words(_TITLE)
    assert "EZT" not in rev
    parsed = RegexParser().parse(rev)
    assert parsed is not None
    assert parsed.title_en == "The Boys"


def test_fill_episode_from_parent_fills_when_missing():
    """文件名无集号时，从父目录名提取季/集（动漫单集目录携带 S01E07）."""
    parsed = RegexParser().parse("Sayonara.Lara.mkv")
    assert parsed is not None
    assert parsed.episode is None
    MediaService._fill_episode_from_parent_paths("/downloads/Sayonara.Lara.S01E07.2026.1080p/Sayonara.Lara.mkv", parsed)
    assert parsed.season == 1
    assert parsed.episode == 7


def test_fill_episode_from_parent_bare_index_overridden():
    """裸数字文件名（1.mkv）解析的索引不是集号，优先用父目录集号覆盖."""
    parsed = RegexParser().parse("1.mkv")
    assert parsed is not None
    MediaService._fill_episode_from_parent_paths("/downloads/Sparks.of.Tomorrow.S02E03.2026.1080p/1.mkv", parsed)
    assert parsed.season == 2
    assert parsed.episode == 3


def test_fill_episode_from_parent_does_not_override_existing():
    """文件名已解析出集号时不覆盖（避免集号冲突）."""
    parsed = RegexParser().parse("Sayonara.Lara.S01E07.2026.1080p.mkv")
    assert parsed is not None
    assert parsed.episode == 7
    MediaService._fill_episode_from_parent_paths(
        "/downloads/Sayonara.Lara.S01.2026.1080p/Sayonara.Lara.S01E07.2026.1080p.mkv", parsed
    )
    assert parsed.season == 1
    assert parsed.episode == 7


def test_fill_episode_from_parent_no_episode_anywhere():
    """文件名与父目录都无集号时不改动."""
    parsed = RegexParser().parse("Some.Movie.2024.1080p.mkv")
    assert parsed is not None
    MediaService._fill_episode_from_parent_paths("/downloads/Some.Movie.2024.1080p/Some.Movie.2024.1080p.mkv", parsed)
    assert parsed.episode is None
