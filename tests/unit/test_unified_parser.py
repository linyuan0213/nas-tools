"""UnifiedParser 端到端测试 — 覆盖现有 test_anime_parser.py 场景"""

import pytest

from app.domain.mediatypes import MediaType
from app.media.parser.unified import UnifiedParser


@pytest.fixture
def parser():
    return UnifiedParser()


class TestDmhyMikanFormat:
    """dmhy/mikan 格式测试 — 与 test_anime_parser.py 保持一致"""

    def test_cn_romaji_bracket_episode(self, parser):
        result = parser.parse("[绿茶字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [04][WebRip][1080p][繁日内嵌]")
        assert result is not None
        assert result.episode == 4
        assert result.resource_pix == "1080p"
        assert result.resource_type == "WEB-DL"
        assert result.title_cn is not None
        assert "穹庐" in result.title_cn

    def test_release_group_not_cn_name(self, parser):
        result = parser.parse("[北宇治字幕组] 穹庐下的魔女 / Tenmaku no Jaadugar [03][WebRip][HEVC_AAC][简日内嵌]")
        assert result is not None
        assert result.episode == 3
        assert result.title_cn is not None
        assert "字幕组" not in (result.title_cn or "")

    def test_en_cn_order_baha_format(self, parser):
        result = parser.parse("[ANi] Tenmaku no Jādūgar /  穹庐下的魔女 - 04 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]")
        assert result is not None
        assert result.episode == 4
        assert result.resource_pix == "1080p"
        assert result.title_cn is not None
        assert "穹庐" in result.title_cn

    def test_dash_episode_format(self, parser):
        result = parser.parse(
            "[绿茶字幕组&LoliHouse] 穹庐下的魔女 / Tenmaku no Jaadugar - 04 "
            "[WebRip 1080p HEVC-10bit AAC][简繁日内封字幕]"
        )
        assert result is not None
        assert result.episode == 4
        assert result.title_cn is not None


class TestTvFormat:
    """电视剧格式测试"""

    def test_sxxexx(self, parser):
        result = parser.parse("Breaking Bad S01E05 1080p BluRay x264 DTS")
        assert result is not None
        assert result.season == 1
        assert result.episode == 5
        assert result.resource_pix == "1080p"
        assert result.type == MediaType.TV

    def test_season_episode_keyword(self, parser):
        result = parser.parse("Show Name Season 2 Episode 3 1080p WEB-DL")
        assert result is not None
        assert result.season == 2
        assert result.episode == 3
        assert result.type == MediaType.TV

    def test_chinese_season_episode(self, parser):
        result = parser.parse("庆余年 第2季 第5集 1080p")
        assert result is not None
        assert result.season == 2
        assert result.episode == 5
        assert result.type == MediaType.TV

    def test_episode_title_after_sxxexx_not_merged_into_title(self, parser):
        """集标题不应并入主标题（Medalist.S02E09.It.Begins → Medalist）"""
        result = parser.parse("Medalist.S02E09.It.Begins.1080p.DSNP.WEB-DL.AAC2.0.H.264-VARYG.mkv")
        assert result is not None
        assert result.title_en == "Medalist"
        assert result.season == 2
        assert result.episode == 9
        assert result.type == MediaType.TV

    def test_episode_title_with_words_after_sxxexx(self, parser):
        result = parser.parse("Golden.Kamuy.S05E01.Town.of.Reunions.1080p.CR.WEB-DL.DUAL.DDP2.0.H.264-Kitsune.mkv")
        assert result is not None
        assert result.title_en == "Golden Kamuy"
        assert result.season == 5
        assert result.episode == 1

    def test_no_episode_title_when_none_present(self, parser):
        result = parser.parse("Witch.Watch.S01E16.1080p.KKTV.WEB-DL.AAC2.0.H.264-CHDWEB.mkv")
        assert result is not None
        assert result.title_en == "Witch Watch"
        assert result.season == 1
        assert result.episode == 16


class TestMovieFormat:
    """电影格式测试"""

    def test_movie_year_resolution(self, parser):
        result = parser.parse("The Matrix 1999 1080p BluRay x264")
        assert result is not None
        assert result.year == "1999"
        assert result.resource_pix == "1080p"
        assert result.type == MediaType.MOVIE

    def test_muhd_source_token_not_glued_into_name(self, parser):
        """FRDS 的 mUHD 标记不应粘进片名（Green Book → 而非 Green Book Muhd）"""
        result = parser.parse("Green.Book.2018.BluRay.2160p.x265.10bit.HDR.3Audio.mUHD-FRDS.mkv")
        assert result is not None
        assert result.title_en == "Green Book"
        assert result.year == "2018"
        assert result.resource_pix == "2160p"
        assert result.resource_team == "FRDS"
        assert "Muhd" not in (result.title_en or "")

    def test_multi_bracket_title_not_overwritten_by_release_note(self, parser):
        """多括号标题（中/英/日 + 发布注释）应取真实标题，而非尾部发布注释"""
        result = parser.parse(
            "[剧场版 鬼灭之刃 无限城篇 第一章 猗窝座再袭]"
            "[Gekijouban Kimetsu no Yaiba Mugen-jou Hen Daiisshou Akaza Sairai]"
            "[劇場版 鬼滅の刃 無限城編 第一章 猗窩座再来]"
            "[BDRip][1920x1080][Movie+SP]"
            "[H264 FLACx2 TrueHD MKV][自壓(付相關專輯)]"
        )
        assert result is not None
        assert result.title_cn is not None
        assert "鬼灭之刃" in result.title_cn
        assert "自压" not in result.title_cn
        assert "相关专辑" not in (result.title_cn or "")
        assert result.resource_pix == "1080p"

    def test_subtitle_tags_not_treated_as_title(self, parser):
        """[JPSC_JPTC] / [SRT] 等字幕标签不应被当成片名"""
        result = parser.parse(
            "[NEST] Mushoku Tensei Jobless Reincarnation S03 - 05 [CR WEB-DL 1080p AVC AAC][JPSC_JPTC].mkv"
        )
        assert result is not None
        assert result.title_en is not None
        assert "Jpsc" not in result.title_en
        assert "Jptc" not in result.title_en
        assert "Mushoku" in result.title_en

        result2 = parser.parse("[Skymoon-Raws] Mushoku Tensei Ⅲ Isekai Ittara Honki Dasu - 06")
        assert result2 is not None
        assert result2.title_en is not None
        assert "srt" not in result2.title_en.lower()
        assert "Mushoku" in result2.title_en

    def test_roman_numeral_season(self, parser):
        """动漫标题中的罗马数字季标（Ⅲ/III）应解析为对应季数"""
        result = parser.parse("[Skymoon-Raws] Mushoku Tensei Ⅲ Isekai Ittara Honki Dasu - 06")
        assert result is not None
        assert result.season == 3
        assert result.episode == 6

        result2 = parser.parse("Mushoku Tensei II Isekai Ittara Honki Dasu - 01")
        assert result2 is not None
        assert result2.season == 2


class TestAnimeFormats:
    """动漫格式测试"""

    def test_bracket_episode(self, parser):
        result = parser.parse("[LoliHouse] Anime Title [08][1080p]")
        assert result is not None
        assert result.episode == 8
        assert result.resource_pix == "1080p"

    def test_chinese_episode(self, parser):
        result = parser.parse("某某动漫 第5集 1080p")
        assert result is not None
        assert result.episode == 5

    def test_chinese_number_episode(self, parser):
        result = parser.parse("某某动漫 第十集 1080p")
        assert result is not None
        assert result.episode == 10

    def test_mikan_format(self, parser):
        result = parser.parse("[喵萌奶茶屋][鬼灭之刃 柱训练篇][1080p][简日双语]")
        assert result is not None
        assert result.title_cn is not None
        assert "鬼灭之刃" in result.title_cn


class TestEdgeCases:
    """边缘案例测试"""

    def test_empty_title(self, parser):
        assert parser.parse("") is None

    def test_no_episode(self, parser):
        result = parser.parse("Movie Title 2008 1080p BluRay")
        assert result is not None
        assert result.episode is None
        assert result.year == "2008"

    def test_episode_range(self, parser):
        result = parser.parse("[Group] Anime Title [01-08][1080p]")
        assert result is not None
        assert result.episode == 1
        assert result.end_episode == 8

    def test_confidence_dynamic(self, parser):
        result = parser.parse("[Group] Anime [05][1080p HEVC AAC]")
        assert result is not None
        assert 0.0 < result.confidence <= 1.0


class TestRegressionIdentify:
    """识别回归 — 2026-08 报告的四例解析失败"""

    def test_subtitle_multiplier_bracket_is_metadata(self, parser):
        """[WebRip 1080p HEVC-10bit AAC ASSx2] 应整体识别为元数据括号"""
        result = parser.parse("[LoliHouse] Clevatess S2 - 03 [WebRip 1080p HEVC-10bit AAC ASSx2].mkv")
        assert result is not None
        assert result.title_en == "Clevatess"
        assert result.season == 2
        assert result.episode == 3

    def test_joint_release_group_bracket_removed(self, parser):
        """多组联合发布 [Studio A&GroupB] 带空格也应作为发布组移除"""
        result = parser.parse(
            "[Studio GreenTea&LoliHouse] Tenmaku no Jaadugar - 05 [WebRip 1080p HEVC-10bit AAC ASSx2].mkv"
        )
        assert result is not None
        assert result.title_en == "Tenmaku No Jaadugar"
        assert result.episode == 5

    def test_year_not_glued_into_name(self, parser):
        """点分隔标题中年份不应并入片名"""
        result = parser.parse("KAIJU.GIRL.CARAMELISE.2026.S01.1080p.FRIDAY.WEB-DL.AAC2.0.H.264-DepWeb")
        assert result is not None
        assert result.title_en == "Kaiju Girl Caramelise"
        assert result.year == "2026"
        assert result.season == 1
