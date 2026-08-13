"""Tests for app.sites.torrent."""

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.sites.torrent import Torrent


class _MediaInfo(MediaInfo):
    def __init__(self, **kwargs):
        super().__init__()
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestTorrentGetDownloadList:
    """Test suite for Torrent.get_download_list."""

    def test_prioritizes_season_pack_over_single_episodes(self):
        single = _MediaInfo(
            title="Single Ep",
            type=MediaType.ANIME,
            tmdb_id=1,
            begin_season=1,
            begin_episode=1,
            end_episode=1,
            res_order=1,
            site_order=1,
            seeders=100,
        )
        pack = _MediaInfo(
            title="Season Pack",
            type=MediaType.ANIME,
            tmdb_id=1,
            begin_season=1,
            res_order=1,
            site_order=1,
            seeders=10,
        )
        result = Torrent.get_download_list([single, pack], download_order="default")
        assert result[0].title == "Season Pack"

    def test_prioritizes_multi_episode_pack(self):
        single = _MediaInfo(
            title="Single Ep",
            type=MediaType.ANIME,
            tmdb_id=1,
            begin_season=1,
            begin_episode=1,
            end_episode=1,
            res_order=1,
            site_order=1,
            seeders=100,
        )
        multi = _MediaInfo(
            title="E01-E12 Pack",
            type=MediaType.ANIME,
            tmdb_id=1,
            begin_season=1,
            begin_episode=1,
            end_episode=12,
            res_order=1,
            site_order=1,
            seeders=50,
        )
        result = Torrent.get_download_list([single, multi], download_order="default")
        assert result[0].title == "E01-E12 Pack"

    def test_site_mode_prefers_lower_pri_site(self):
        """site_order=100-pri（pri 越小=主站越优先）：site 模式应选 pri 小（site_order 大）的站点"""
        low = _MediaInfo(
            title="Low",
            type=MediaType.MOVIE,
            res_order=0,
            site_order=99,
            seeders=5,
        )
        high = _MediaInfo(
            title="High",
            type=MediaType.MOVIE,
            res_order=0,
            site_order=-21,
            seeders=500,
        )
        result = Torrent.get_download_list([low, high], download_order="site")
        assert result[0].title == "Low"

    def test_seeder_mode_tie_prefers_lower_pri_site(self):
        """seeder 模式种子数相同时，主站（pri 小、site_order 大）胜出"""
        low = _MediaInfo(
            title="Low",
            type=MediaType.MOVIE,
            res_order=0,
            site_order=99,
            seeders=5,
        )
        high = _MediaInfo(
            title="High",
            type=MediaType.MOVIE,
            res_order=0,
            site_order=-21,
            seeders=5,
        )
        result = Torrent.get_download_list([low, high], download_order="seeder")
        assert result[0].title == "Low"
