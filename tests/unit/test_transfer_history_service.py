"""TransferHistoryService 单元测试."""

from unittest.mock import MagicMock

import pytest

from app.services.transfer_history_service import TransferHistoryService


class _HistoryMock:
    def as_dict(self):
        return {
            "id": 1,
            "mode": "link",
            "source_path": "/src",
            "source_filename": "movie.mkv",
            "dest": "/dst",
        }


class _UnknownMock:
    ID: int = 10
    PATH: str | None = "C:\\unknown\\file.mkv"
    DEST: str = "C:\\dst"
    MODE: str = "copy"


@pytest.fixture
def mock_filetransfer():
    return MagicMock()


@pytest.fixture
def mock_sync_service():
    return MagicMock()


@pytest.fixture
def service(mock_filetransfer, mock_sync_service):
    svc = TransferHistoryService(
        filetransfer=mock_filetransfer,
        sync_service=mock_sync_service,
        cache_ttl=30,
    )
    svc._cache.clear()
    return svc


class TestTransferHistoryService:
    def test_get_transfer_history_page_defaults(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_history.return_value = None
        result = service.get_transfer_history_page("", None, None)
        assert result.total == 0
        assert result.result == []
        assert result.page_num == 30
        assert result.current_page == 1
        assert result.total_page == 1

    def test_get_transfer_history_page_with_data(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_history.return_value = (65, [_HistoryMock()])
        result = service.get_transfer_history_page("", 2, 20)
        assert result.total == 65
        assert result.current_page == 2
        assert result.page_num == 20
        assert result.total_page == 4
        assert result.result[0]["SYNC_MODE"] == "link"
        assert result.result[0]["RMT_MODE"] == "link"

    def test_get_transfer_statistics(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_statistics.return_value = [
            ("movie", "2024-01-01", 5),
            ("tv", "2024-01-01", 3),
            ("anime", "2024-01-02", 2),
        ]
        mock_filetransfer.get_transfer_series_statistics.return_value = [
            ("2024-01-01", 2),
        ]
        result = service.get_transfer_statistics(days=7)
        assert result["labels"] == ["2024-01-01", "2024-01-02"]
        assert result["movie_nums"] == [5, 0]
        assert result["tv_nums"] == [3, 0]
        assert result["anime_nums"] == [0, 2]
        assert result["tv_series_nums"] == [2, 0]

    def test_get_transfer_statistics_skips_empty(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_statistics.return_value = [
            ("movie", "2024-01-01", 0),
            ("unknown", "2024-01-01", 1),
        ]
        mock_filetransfer.get_transfer_series_statistics.return_value = []
        result = service.get_transfer_statistics()
        assert result["labels"] == []
        assert result["movie_nums"] == []
        assert result["tv_nums"] == []
        assert result["anime_nums"] == []
        assert result["tv_series_nums"] == []

    def test_get_transfer_statistics_series_none(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_statistics.return_value = [
            ("tv", "2024-01-01", 4),
        ]
        mock_filetransfer.get_transfer_series_statistics.return_value = None
        result = service.get_transfer_statistics(days=7)
        assert result["tv_series_nums"] == [0]

    def test_get_unknown_list(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_unknown_paths.return_value = [_UnknownMock()]
        mock_filetransfer.get_sync_backend_by_dest.return_value = "smb"
        result = service.get_unknown_list()
        assert len(result) == 1
        assert result[0]["path"] == "C:/unknown/file.mkv"
        assert result[0]["to"] == "C:/dst"
        assert result[0]["dst_backend"] == "smb"

    def test_get_unknown_list_skips_empty_path(self, service, mock_filetransfer):
        empty = _UnknownMock()
        empty.PATH = None
        mock_filetransfer.get_transfer_unknown_paths.return_value = [empty]
        result = service.get_unknown_list()
        assert result == []

    def test_get_unknown_list_by_page(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_unknown_paths_by_page.return_value = (1, [_UnknownMock()])
        mock_filetransfer.get_sync_backend_by_dest.return_value = "local"
        result = service.get_unknown_list_by_page("", 1, 10)
        assert result.total == 1
        assert result.items[0]["path"] == "C:/unknown/file.mkv"

    def test_re_identify_unknown(self, service, mock_filetransfer, mock_sync_service):
        rec = _UnknownMock()
        rec.PATH = "/some/path.mkv"
        mock_filetransfer.get_transfer_unknown_paths.return_value = [rec]
        count = service.re_identify_unknown()
        assert count == 1
        mock_sync_service.re_identify_items.assert_called_once_with(flag="unidentification", ids=[10])

    def test_re_identify_unknown_empty(self, service, mock_filetransfer, mock_sync_service):
        mock_filetransfer.get_transfer_unknown_paths.return_value = []
        count = service.re_identify_unknown()
        assert count == 0
        mock_sync_service.re_identify_items.assert_not_called()

    def test_clear_history(self, service, mock_filetransfer):
        service.clear_history()
        mock_filetransfer.delete_transfer.assert_called_once()
        mock_filetransfer.truncate_transfer_blacklist.assert_called_once()


class TestTransferHistoryServiceCache:
    def test_get_transfer_history_page_uses_cache(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_history.return_value = (65, [_HistoryMock()])
        first = service.get_transfer_history_page("", 2, 20)
        second = service.get_transfer_history_page("", 2, 20)
        assert first == second
        mock_filetransfer.get_transfer_history.assert_called_once()

    def test_get_transfer_statistics_uses_cache(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_statistics.return_value = [("movie", "2024-01-01", 5)]
        first = service.get_transfer_statistics(days=7)
        second = service.get_transfer_statistics(days=7)
        assert first == second
        mock_filetransfer.get_transfer_statistics.assert_called_once()

    def test_get_unknown_list_uses_cache(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_unknown_paths.return_value = [_UnknownMock()]
        mock_filetransfer.get_sync_backend_by_dest.return_value = "local"
        first = service.get_unknown_list()
        second = service.get_unknown_list()
        assert first == second
        mock_filetransfer.get_transfer_unknown_paths.assert_called_once()

    def test_get_unknown_list_by_page_uses_cache(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_unknown_paths_by_page.return_value = (1, [_UnknownMock()])
        mock_filetransfer.get_sync_backend_by_dest.return_value = "local"
        first = service.get_unknown_list_by_page("", 1, 10)
        second = service.get_unknown_list_by_page("", 1, 10)
        assert first == second
        mock_filetransfer.get_transfer_unknown_paths_by_page.assert_called_once()

    def test_clear_history_clears_cache(self, service, mock_filetransfer):
        mock_filetransfer.get_transfer_unknown_paths.return_value = [_UnknownMock()]
        mock_filetransfer.get_sync_backend_by_dest.return_value = "local"
        service.get_unknown_list()
        service.clear_history()
        mock_filetransfer.get_transfer_unknown_paths.return_value = []
        result = service.get_unknown_list()
        assert result == []
        assert mock_filetransfer.get_transfer_unknown_paths.call_count == 2
