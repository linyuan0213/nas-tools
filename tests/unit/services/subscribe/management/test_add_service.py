"""订阅重订阅续订点推导测试（修复：转移历史已到 N 集，前端回传旧 current_ep 导致进度卡住）."""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.media.models import MediaInfo
from app.services.subscribe.management.add_service import SubscribeAddService


class _FakeTransferHistory:
    def __init__(self, contiguous):
        self._contiguous = contiguous

    def get_contiguous_transferred_episode_by_tmdb(self, tmdbid, season=None, start=1):
        return self._contiguous


class _FakeDownloadRepo:
    def __init__(self, contiguous):
        self._contiguous = contiguous

    def get_contiguous_completed_episode_by_tmdb(self, tmdb_id, season=None, start=1):
        return self._contiguous


def _build_service(transfer_contiguous=0, download_contiguous=0):
    svc = SubscribeAddService.__new__(SubscribeAddService)
    svc._movie_repo = MagicMock()
    svc._tv_repo = MagicMock()
    svc._media = MagicMock()
    svc._media.get_tmdb_tv_seasons.return_value = [{"season_number": 1, "episode_count": 48}]
    svc._message = MagicMock()
    svc._event_bus = MagicMock()
    svc._system_config = MagicMock()
    svc._web_utils = MagicMock()
    svc._transfer_history_manager = _FakeTransferHistory(transfer_contiguous)
    svc._download_repo = _FakeDownloadRepo(download_contiguous)
    svc._tv_repo.insert.return_value = 999
    svc._tv_repo.insert_movies.return_value = 999
    return svc


def _make_media_info(tmdb_id=223564):
    mi = MediaInfo()
    mi.tmdb_id = tmdb_id
    mi.type = MediaType.TV
    mi.begin_season = 1
    mi.title = "超超超超超喜欢你的100个女朋友"
    mi.total_episodes = 48
    mi.tmdb_info = {"id": tmdb_id, "name": mi.title, "season": 1}
    return mi


class TestResubscribeContinuation:
    def test_stale_current_ep_bumped_by_transfer_history(self):
        """转移历史已连续 30 集，前端回传旧 current_ep=26 → 应续订到 31（不重复下载已转移集）."""
        svc = _build_service(transfer_contiguous=30)
        svc._media.get_media_info.return_value = _make_media_info()
        svc._media.get_tmdb_season_episodes_num.return_value = 48
        code, msg, media = svc.add_rss_subscribe(
            name="超超超超超喜欢你的100个女朋友",
            year="2023",
            mtype=MediaType.TV,
            season=1,
            total_ep=48,
            current_ep=26,  # 前端回传旧进度
        )
        assert code == 0
        # current_ep 应被历史推导推高到 31（30 集已转移 → 首个待下载 = 31）
        inserted_kw = svc._tv_repo.insert.call_args.kwargs
        assert inserted_kw["current_ep"] == 31
        # lack = 48 - 31 + 1 = 18
        assert inserted_kw["lack"] == 18

    def test_explicit_higher_current_ep_preserved(self):
        """显式指定更高的 current_ep（用户主动从 40 开始）不被历史推导拉低."""
        svc = _build_service(transfer_contiguous=30)
        svc._media.get_media_info.return_value = _make_media_info()
        svc._media.get_tmdb_season_episodes_num.return_value = 48
        code, _, _ = svc.add_rss_subscribe(
            name="测试",
            year="2023",
            mtype=MediaType.TV,
            season=1,
            total_ep=48,
            current_ep=40,
        )
        inserted_kw = svc._tv_repo.insert.call_args.kwargs
        assert inserted_kw["current_ep"] == 40
        assert inserted_kw["lack"] == 9  # 48 - 40 + 1

    def test_no_history_uses_current_ep(self):
        """无转移/下载历史时，沿用传入的 current_ep."""
        svc = _build_service(transfer_contiguous=0, download_contiguous=0)
        svc._media.get_media_info.return_value = _make_media_info()
        svc._media.get_tmdb_season_episodes_num.return_value = 48
        code, _, _ = svc.add_rss_subscribe(
            name="测试", year="2023", mtype=MediaType.TV, season=1, total_ep=48, current_ep=5
        )
        inserted_kw = svc._tv_repo.insert.call_args.kwargs
        assert inserted_kw["current_ep"] == 5

    def test_history_bumps_from_download_history(self):
        """下载历史连续集也可作为续订点（转移历史为空时）."""
        svc = _build_service(transfer_contiguous=0, download_contiguous=25)
        svc._media.get_media_info.return_value = _make_media_info()
        svc._media.get_tmdb_season_episodes_num.return_value = 48
        code, _, _ = svc.add_rss_subscribe(
            name="测试", year="2023", mtype=MediaType.TV, season=1, total_ep=48, current_ep=10
        )
        inserted_kw = svc._tv_repo.insert.call_args.kwargs
        assert inserted_kw["current_ep"] == 26
