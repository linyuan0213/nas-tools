r"""文件名季集解析回归测试（分辨率粘连修复）.

S01E071080p（集号与 1080p 分辨率粘连）应解析为 S01E07，
此前 \d+ 贪婪把 07+1080 全当集号（ep=71080）。
"""

from app.media.parser._metainfo import meta_info


class TestResolutionTightEpisode:
    """集号与分辨率粘连（S01E07+1080p）解析"""

    def test_episode_tight_with_resolution(self):
        p = meta_info("Sparks.of.Tomorrow.S01E071080p.NF.WEB-DL.AAC2.0.H.264-MWeb.mkv")
        assert p.begin_season == 1
        assert p.begin_episode == 7

    def test_episode_tight_resolution_two_digit(self):
        p = meta_info("Some.Show.S01E121080p.NF.WEB-DL.mkv")
        assert p.begin_season == 1
        assert p.begin_episode == 12

    def test_episode_normal_with_dot_resolution(self):
        p = meta_info("Sparks.of.Tomorrow.S01E07.1080p.NF.WEB-DL.AAC2.0.H.264-MWeb.mkv")
        assert p.begin_episode == 7

    def test_episode_normal_year_separated(self):
        p = meta_info("Though.I.Am.an.Inept.Villainess.S01E06.2026.1080p.NF.WEB-DL.H.264.AAC2.0-HHWEB.mkv")
        assert p.begin_episode == 6

    def test_episode_plain(self):
        p = meta_info("Some.Show.S01E07.mkv")
        assert p.begin_episode == 7

    def test_episode_range_still_wins(self):
        """范围规则（S01E01-E12）优先于分辨率粘连规则"""
        p = meta_info("Some.Show.S01E01-E12.1080p.mkv")
        assert p.begin_episode == 1
        assert p.end_episode == 12
