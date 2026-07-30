"""统一解析引擎测试"""

import pytest

from app.media.parser.unified.rules import get_rule_engine
from app.media.parser.unified.types import ParseContext


@pytest.fixture
def engine():
    return get_rule_engine()


def parse(engine, title: str) -> ParseContext:
    ctx = ParseContext(text=title)
    return engine.apply(ctx)


class TestEpisodeRules:
    def test_sxxexx(self, engine):
        ctx = parse(engine, "Breaking Bad S01E05 1080p BluRay")
        assert ctx.episode == 5
        assert ctx.season == 1

    def test_bracket_ep(self, engine):
        ctx = parse(engine, "[LoliHouse] Anime Title [08][1080p]")
        assert ctx.episode == 8

    def test_chinese_ep(self, engine):
        ctx = parse(engine, "某某动漫 第5集 1080p")
        assert ctx.episode == 5

    def test_chinese_number_ep(self, engine):
        ctx = parse(engine, "某某动漫 第十集 1080p")
        assert ctx.episode == 10

    def test_dash_ep(self, engine):
        ctx = parse(engine, "Anime Title - 05 [1080p]")
        assert ctx.episode == 5

    def test_ep_prefix(self, engine):
        ctx = parse(engine, "Title EP05 1080p")
        assert ctx.episode == 5


class TestSeasonRules:
    def test_sxx(self, engine):
        ctx = parse(engine, "Show Name S02 1080p")
        assert ctx.season == 2

    def test_chinese_season(self, engine):
        ctx = parse(engine, "电视剧 第3季 1080p")
        assert ctx.season == 3

    def test_season_keyword(self, engine):
        ctx = parse(engine, "Show Season 1 1080p")
        assert ctx.season == 1


class TestYearRules:
    def test_bracket_year(self, engine):
        ctx = parse(engine, "Movie Title [2008] 1080p")
        assert ctx.year == "2008"

    def test_bare_year(self, engine):
        ctx = parse(engine, "Movie Title 2008 1080p")
        assert ctx.year == "2008"


class TestResolutionRules:
    def test_1080p(self, engine):
        ctx = parse(engine, "Title 1080p")
        assert ctx.resolution == "1080p"

    def test_4k(self, engine):
        ctx = parse(engine, "Title 4K")
        assert ctx.resolution == "2160p"

    def test_pixel_format(self, engine):
        ctx = parse(engine, "Title 1920x1080")
        assert ctx.resolution == "1080p"


class TestCodecRules:
    def test_hevc(self, engine):
        ctx = parse(engine, "Title 1080p HEVC")
        assert ctx.video_codec == "HEVC"

    def test_h264(self, engine):
        ctx = parse(engine, "Title 1080p H.264")
        assert ctx.video_codec == "H.264"

    def test_aac(self, engine):
        ctx = parse(engine, "Title 1080p AAC")
        assert ctx.audio_codec == "AAC"

    def test_dts(self, engine):
        ctx = parse(engine, "Title 1080p DTS-HD MA")
        assert ctx.audio_codec == "DTS-HD MA"


class TestSourceRules:
    def test_webdl(self, engine):
        ctx = parse(engine, "Title WEB-DL 1080p")
        assert ctx.source == "WEB-DL"

    def test_bluray(self, engine):
        ctx = parse(engine, "Title BluRay 1080p")
        assert ctx.source == "BluRay"

    def test_hdtv(self, engine):
        ctx = parse(engine, "Title HDTV 1080p")
        assert ctx.source == "HDTV"


class TestCombinedParsing:
    def test_anime_dmhy_format(self, engine):
        ctx = parse(engine, "[绿茶字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [04][WebRip][1080p]")
        assert ctx.episode == 4
        assert ctx.resolution == "1080p"
        assert ctx.source == "WEB-DL"

    def test_tv_sxxexx_format(self, engine):
        ctx = parse(engine, "Breaking Bad S01E05 1080p BluRay x264 DTS")
        assert ctx.season == 1
        assert ctx.episode == 5
        assert ctx.resolution == "1080p"
        assert ctx.source == "BluRay"
        assert ctx.video_codec == "H.264"
        assert ctx.audio_codec == "DTS"

    def test_anime_baha_format(self, engine):
        ctx = parse(engine, "[ANi] Tenmaku no Jādūgar /  穹庐下的魔女 - 04 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]")
        assert ctx.episode == 4
        assert ctx.resolution == "1080p"
        assert ctx.source == "WEB-DL"
        assert ctx.audio_codec == "AAC"
        assert ctx.video_codec == "H.264"
