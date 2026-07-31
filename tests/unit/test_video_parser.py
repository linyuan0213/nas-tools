"""测试统一解析引擎 — 电视剧/影视格式"""

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.media.parser._release_groups import ReleaseGroupsMatcher
from app.media.parser.unified import UnifiedParser


def _parse(title: str) -> MediaInfo:
    result = UnifiedParser().parse(title)
    return MediaInfo.from_parser(result) if result else MediaInfo()


class TestVideoParserFix:
    def test_bracket_episode(self):
        result = _parse("[05] Title 1080p.mkv")
        assert result.begin_episode == 5
        assert result.type == MediaType.TV

    def test_bracket_episode_no_match_no_digits(self):
        result = _parse("[abc] Title 1080p.mkv")
        assert result.begin_episode is None


class TestChineseSeasonDetection:
    def test_chinese_single_season(self):
        result = _parse("Show 第2季")
        assert result.begin_season == 2
        assert result.type == MediaType.TV

    def test_chinese_season_range(self):
        result = _parse("Show 第1-3季")
        assert result.begin_season == 1
        assert result.end_season == 3
        assert result.type == MediaType.TV

    def test_multitoken_chinese_season(self):
        result = _parse("Show [1080p] 第1季")
        assert result.begin_season == 1


class TestChineseEpisodeDetection:
    def test_chinese_episode(self):
        result = _parse("Show 第05集")
        assert result.begin_episode == 5
        assert result.type == MediaType.TV

    def test_chinese_episode_range(self):
        result = _parse("Show 第01-05集")
        assert result.begin_episode is not None
        assert result.type == MediaType.TV

    def test_chinese_episode_with_tags(self):
        result = _parse("Show [1080p] 第08集.mkv")
        assert result.begin_episode == 8


class TestWebSourceDetection:
    def test_amzn_source(self):
        result = _parse("Show.S01E01.AMZN.WEB-DL.1080p")
        assert result.type == MediaType.TV

    def test_nf_source(self):
        result = _parse("Show.S01E01.NF.WEB-DL.1080p")
        assert result.type == MediaType.TV


class TestSeasonEpisodeStandard:
    def test_standard_s01e01(self):
        result = _parse("Show.S01E01.1080p")
        assert result.begin_season == 1
        assert result.begin_episode == 1
        assert result.type == MediaType.TV

    def test_bare_multi_episode_range(self):
        result = _parse("Show.E01-E05.1080p")
        assert result.begin_episode == 1
        assert result.end_episode == 5

    def test_multi_season_pack(self):
        result = _parse("Show.S01-S03.1080p.BluRay")
        assert result.begin_season == 1
        assert result.end_season == 3

    def test_audio_token_not_episode(self):
        result = _parse("Dr.STONE.S04.2025.1080p.BluRay.x265.10bit.FLAC.2.0.2Audio-ADE")
        assert result.begin_season == 4
        assert result.begin_episode is None
        assert result.type == MediaType.TV


class TestReleaseGroups:
    def test_ntb_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[NTb] Show.S01E01.1080p")
        assert "NTb" in result

    def test_qxr_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[QxR] Show.S01E01.1080p")
        assert "QxR" in result

    def test_rar_bg_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[RARBG] Show.S01E01.1080p")
        assert "RARBG" in result

    def test_vcb_in_anime(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[VCB-Studio] Anime [BDRip]")
        assert "VCB-Studio" in result


class TestCRCNotEpisode:
    def test_crc_e859_not_episode(self):
        """CRC 标签中的数字不应被误判为集号"""
        result = _parse(
            "[Yameii] Witch Hat Atelier - S01E13 [English Dub]"
            " [CR WEB-DL 1080p H264 AAC] [EE32E859] (Tongari Boushi no Atelier)"
        )
        assert result.begin_episode == 13
        assert result.end_episode is None
