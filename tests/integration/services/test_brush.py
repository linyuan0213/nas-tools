"""Tests for app.services.brush package."""

from datetime import time as dtime
from unittest.mock import MagicMock, patch

from app.services.brush.helpers import BrushTaskHelper
from app.services.brush.repository import BrushTaskRepository
from app.services.brush.scheduler import BrushTaskScheduler


class TestBrushTaskRepository:
    """Test suite for BrushTaskRepository."""

    def test_get_brushtasks_delegates(self):
        mock_repo = MagicMock()
        mock_repo.get_brushtasks.return_value = []
        repo = BrushTaskRepository(mock_repo)
        result = repo.get_brushtasks(brush_id=1)
        mock_repo.get_brushtasks.assert_called_once_with(brush_id=1)
        assert result == []

    def test_get_brushtask_totalsize_delegates(self):
        mock_repo = MagicMock()
        mock_repo.get_brushtask_totalsize.return_value = 100
        repo = BrushTaskRepository(mock_repo)
        result = repo.get_brushtask_totalsize(1)
        mock_repo.get_brushtask_totalsize.assert_called_once_with(1)
        assert result == 100

    def test_insert_brushtask_torrent_converts_types(self):
        mock_repo = MagicMock()
        repo = BrushTaskRepository(mock_repo)
        repo.insert_brushtask_torrent(1, "title", "enc", 2, "dlid", 1024)
        mock_repo.insert_brushtask_torrent.assert_called_once_with(
            brush_id=1, title="title", enclosure="enc", downloader="2", download_id="dlid", size="1024", page_url=""
        )

    def test_delete_brushtask_defaults_zero(self):
        mock_repo = MagicMock()
        repo = BrushTaskRepository(mock_repo)
        repo.delete_brushtask(None)
        mock_repo.delete_brushtask.assert_called_once_with(0)

    def test_update_brushtask_state_defaults_empty(self):
        mock_repo = MagicMock()
        repo = BrushTaskRepository(mock_repo)
        repo.update_brushtask_state(None, None)
        mock_repo.update_brushtask_state.assert_called_once_with(tid=None, state="")


class TestBrushTaskScheduler:
    """Test suite for BrushTaskScheduler."""

    def test_start_job_delegates(self):
        mock_scheduler = MagicMock()
        sched = BrushTaskScheduler(mock_scheduler)

        def func():
            pass

        sched.start_job(func, "test", (), "id1", "interval", {"seconds": 60})
        mock_scheduler.start_job.assert_called_once()
        args = mock_scheduler.start_job.call_args[0][0]
        assert args["job_id"] == "id1"
        assert args["trigger"] == "interval"
        assert args["jobstore"] == "brushtask"

    def test_remove_job_suppresses_exception(self):
        mock_scheduler = MagicMock()
        mock_scheduler.remove_job.side_effect = ValueError("not found")
        sched = BrushTaskScheduler(mock_scheduler)
        sched.remove_job("id1")
        mock_scheduler.remove_job.assert_called_once_with("id1", jobstore="brushtask")

    def test_remove_all_jobs_delegates(self):
        mock_scheduler = MagicMock()
        sched = BrushTaskScheduler(mock_scheduler)
        sched.remove_all_jobs()
        mock_scheduler.remove_all_jobs.assert_called_once_with(jobstore="brushtask")

    def test_remove_all_jobs_suppresses_exception(self):
        mock_scheduler = MagicMock()
        mock_scheduler.remove_all_jobs.side_effect = Exception("boom")
        sched = BrushTaskScheduler(mock_scheduler)
        sched.remove_all_jobs()


class TestBrushTaskHelper:
    """Test suite for BrushTaskHelper."""

    def test_parse_json_rule_empty(self):
        assert BrushTaskHelper.parse_json_rule(None) == {}
        assert BrushTaskHelper.parse_json_rule("") == {}

    def test_parse_json_rule_valid_json(self):
        assert BrushTaskHelper.parse_json_rule('{"a": 1}') == {"a": 1}

    def test_parse_json_rule_wrapped_quotes(self):
        assert BrushTaskHelper.parse_json_rule("'{\"a\": 1}'") == {"a": 1}

    def test_parse_json_rule_invalid_returns_default(self):
        assert BrushTaskHelper.parse_json_rule("not json", default={"default": True}) == {"default": True}

    def test_is_in_time_range_empty(self):
        assert BrushTaskHelper.is_in_time_range("") is True

    def test_is_in_time_range_invalid_format(self):
        assert BrushTaskHelper.is_in_time_range("invalid") is False

    def test_is_torrent_handled_empty_enclosure(self):
        helper = BrushTaskHelper(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert helper.is_torrent_handled(None) is False
        assert helper.is_torrent_handled("") is False

    def test_is_allow_new_torrent_empty_task(self):
        helper = BrushTaskHelper(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert helper.is_allow_new_torrent(None, 0) is False

    def test_is_allow_new_torrent_seed_size_exceeded(self):
        repo = MagicMock()
        repo.get_brushtask_totalsize.return_value = 10 * 1024**3
        helper = BrushTaskHelper(repo, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        taskinfo = {"id": 1, "name": "test", "seed_size": 5, "downloader": 1, "downloader_name": "qbit"}
        assert helper.is_allow_new_torrent(taskinfo, 0) is False

    def test_is_allow_new_torrent_dlcount_exceeded(self):
        repo = MagicMock()
        repo.get_brushtask_totalsize.return_value = 0
        downloader = MagicMock()
        downloader.get_downloading_torrents.return_value = [1, 2, 3]
        helper = BrushTaskHelper(repo, downloader, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        taskinfo = {"id": 1, "name": "test", "seed_size": 100, "downloader": 1, "downloader_name": "qbit"}
        assert helper.is_allow_new_torrent(taskinfo, 2) is False

    def test_get_downloading_count(self):
        downloader = MagicMock()
        downloader.get_downloading_torrents.return_value = [1, 2]
        helper = BrushTaskHelper(MagicMock(), downloader, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert helper.get_downloading_count(1) == 2

    def test_get_downloading_count_none(self):
        downloader = MagicMock()
        downloader.get_downloading_torrents.return_value = None
        helper = BrushTaskHelper(MagicMock(), downloader, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        # 下载器不可达时返回 None（调用方据此提前中止，而非当作 0 放行）
        assert helper.get_downloading_count(1) is None

    def test_download_torrent_no_enclosure(self):
        helper = BrushTaskHelper(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert helper.download_torrent({}, {}, {}, "title", None, 0, "") is False


class TestTimeRangeCrossDay:
    """is_in_time_range 跨天时间段测试."""

    @staticmethod
    def _now_at(hour: int, minute: int = 0):
        class _FakeNow:
            @staticmethod
            def time():
                return dtime(hour, minute)

        return _FakeNow

    def test_same_day_in_range(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(10, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00") is True

    def test_same_day_before_range(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(6, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00") is False

    def test_same_day_after_range(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(20, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00") is False

    def test_same_day_at_boundary(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(8, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00") is True
            mock_dt.now.return_value = self._now_at(18, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00") is True

    def test_cross_day_midnight(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(23, 0)
            assert BrushTaskHelper.is_in_time_range("22:00-06:00") is True

    def test_cross_day_early_morning(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(3, 0)
            assert BrushTaskHelper.is_in_time_range("22:00-06:00") is True

    def test_cross_day_outside_range(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(12, 0)
            assert BrushTaskHelper.is_in_time_range("22:00-06:00") is False

    def test_cross_day_at_boundary(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(22, 0)
            assert BrushTaskHelper.is_in_time_range("22:00-06:00") is True
            mock_dt.now.return_value = self._now_at(6, 0)
            assert BrushTaskHelper.is_in_time_range("22:00-06:00") is True

    def test_multiple_periods_with_cross_day(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(3, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00,22:00-06:00") is True

    def test_multiple_periods_outside_all(self):
        with patch("app.services.brush.helpers.datetime") as mock_dt:
            mock_dt.now.return_value = self._now_at(20, 0)
            assert BrushTaskHelper.is_in_time_range("08:00-18:00,22:00-06:00") is False
