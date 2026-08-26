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

    def test_hyphenated_number_in_title_not_episode(self, parser):
        """标题复合词中的数字（100-nin）不得识别为集号"""
        result = parser.parse(
            "Kimi no Koto ga Dai Dai Dai Dai Daisuki na 100-nin no Kanojo S01 1080p BluRay x265 FLAC 2.0-7³ACG"
        )
        assert result is not None
        assert result.season == 1
        assert result.episode is None

    def test_hyphenated_number_web_dl_variant(self, parser):
        result = parser.parse(
            "Kimi no Koto ga Dai Dai Dai Dai Daisuki na 100-nin no Kanojo S01 2023 "
            "1080p CR WEB-DL x264 AAC-AnimeS@ADWeb"
        )
        assert result is not None
        assert result.episode is None

    def test_number_followed_by_name_word_not_episode(self, parser):
        """The 100 Girlfriends：数字后跟普通单词属于标题词，不是集号"""
        result = parser.parse(
            "The 100 Girlfriends Who Really Really Really Really REALLY Love You S01 2023 "
            "1080p Baha WEB-DL AAC H264-HHWEB"
        )
        assert result is not None
        assert result.season == 1
        assert result.episode is None
        assert "100" in (result.title_en or "")

    def test_bare_episode_before_tech_token_still_works(self, parser):
        """裸集号后紧跟技术信息仍应识别"""
        result = parser.parse("Some Anime Title 05 1080p WEB-DL AAC")
        assert result is not None
        assert result.episode == 5


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


class TestSiteMarkerStripping:
    """公开站种子中的站点/发布站标记不应抢占片名"""

    def test_bracket_domain_marker(self, parser):
        """[EZTVx.to] 应被剥离，片名为 The Boys"""
        result = parser.parse("The.Boys.S04E08.1080p.HEVC.x265-MeGusta[EZTVx.to].mkv")
        assert result is not None
        assert result.title_en == "The Boys"
        assert result.season == 4
        assert result.episode == 8

    def test_bracket_domain_marker_lowercase(self, parser):
        result = parser.parse("the.boys.s04e02.1080p.web.h264-successfulcrab[EZTVx.to].mkv")
        assert result is not None
        assert result.title_en == "The Boys"
        assert result.season == 4
        assert result.episode == 2

    def test_www_domain_prefix(self, parser):
        """www.UIndex.org 水印应被剥离，片名为 FBI"""
        result = parser.parse("www.UIndex.org    -    FBI.S08E16.1080p.WEB.h264-ETHEL")
        assert result is not None
        assert result.title_en == "Fbi"
        assert result.season == 8
        assert result.episode == 16

    def test_other_domain_markers(self, parser):
        """其他常见站点标记也应剥离"""
        for title in (
            "Game.of.Thrones.S01E01.1080p.WEB-DL[rarbg.to].mkv",
            "House.of.the.Dragon.S02E01.1080p[rarbg.to].mkv",
            "Breaking.Bad.S05E16.1080p.WEB-DL[x265.YIFY].mkv",
        ):
            result = parser.parse(title)
            assert result is not None, title

    def test_real_title_with_dot_not_stripped(self, parser):
        """带点号的真实剧名不应被误剥（Parks.and.Recreation）"""
        result = parser.parse("Parks.and.Recreation.S01E01.720p.WEB-DL.mkv")
        assert result is not None
        assert result.title_en == "Parks And Recreation"
        assert result.season == 1
        assert result.episode == 1

    def test_movie_single_extension_not_stripped(self, parser):
        """Avatar.mkv 不应因类域名形态被误剥（容器扩展名非站点 TLD）"""
        result = parser.parse("Avatar.2010.mkv")
        assert result is not None
        assert result.title_en == "Avatar"
        assert result.year == "2010"


class TestSharedPostProcess:
    """MediaService._post_process 应让所有识别入口共用同一套后处理"""

    def _service(self):
        from typing import cast

        from app.media.lookup.tmdb_lookup import TmdbLookup
        from app.media.parser.regex import RegexParser
        from app.media.service import MediaService

        return MediaService(tmdb_lookup=cast(TmdbLookup, object()), llm_parser=RegexParser())

    def test_glue_fix_keeps_real_title(self, parser):
        """'Sparks of Tomorrow' 的 Sparks 不被发布组剥离，集名粘连修复应保留完整标题"""
        svc = self._service()
        title = "Sparks. of. Tomorrow. S01E06. 2026. 1080p. NF. WEB-DL. AHD"
        parsed = parser.parse(title)
        assert parsed.title_en == "Sparks Of Tomorrow"
        post = svc._post_process(parsed, title)
        assert post is not None and post.title_en is not None
        assert post.title_en.lower() == "sparks of tomorrow"
        assert post.season == 1 and post.episode == 6 and post.year == "2026"

    def test_year_extracted_from_name_tail(self, parser):
        """标题末尾年份应被提取为 year 并从标题剥离"""
        svc = self._service()
        parsed = parser.parse("Some Title 2019 S01E01 720p WEB-DL")
        post = svc._post_process(parsed, "Some Title 2019 S01E01 720p WEB-DL")
        assert post is not None
        assert post.year == "2019"

    def test_subtitle_does_not_overwrite_title_en(self, parser):
        """无意义父目录（如 /tmp）解析出的英文名不应覆盖真实标题"""
        svc = self._service()
        title = "Sparks. of. Tomorrow. S01E06. 2026. 1080p. NF. WEB-DL. AHD"
        parsed = parser.parse(title)
        post = svc._post_process(parsed, title, "tmp /")
        assert post is not None and post.title_en is not None
        assert post.title_en.lower() == "sparks of tomorrow"
