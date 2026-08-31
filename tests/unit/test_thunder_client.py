"""Thunder 客户端拆包下载功能测试"""

from unittest.mock import MagicMock, patch

from app.domain.mediatypes import MediaType
from app.plugin_framework.builtin_plugins.dl_thunder.backend.download_client import Thunder

_PY_THUNDER = "app.plugin_framework.builtin_plugins.dl_thunder.backend.download_client.PyThunder"


class MockMediaInfo:
    """Mock 媒体信息对象"""

    def __init__(self, **kwargs):
        self.type = kwargs.get("type", MediaType.TV)
        self.title = kwargs.get("title", "Test Show")
        self.tmdb_id = kwargs.get("tmdb_id", 12345)
        self.enclosure = kwargs.get("enclosure", "https://example.com/torrent")
        self.page_url = kwargs.get("page_url", "https://example.com/page")
        self.org_string = kwargs.get("org_string", "Test.Show.S01.1080p")
        self.save_path = kwargs.get("save_path", None)
        self.download_setting = kwargs.get("download_setting", None)
        self.size = kwargs.get("size", 0)
        self.category = kwargs.get("category", "")

    def get_season_list(self):
        return [1]

    def get_episode_list(self):
        return []

    def to_dict(self):
        return {"title": self.title, "type": self.type.value}


class TestThunderResolveTid:
    def test_resolve_tid_without_mapping(self):
        client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
        assert client._resolve_tid("task-1") == "task-1"

    def test_resolve_tid_with_mapping(self):
        client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
        client._recreated_tasks["old-task"] = "new-task"
        assert client._resolve_tid("old-task") == "new-task"

    def test_resolve_tid_none(self):
        client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
        assert client._resolve_tid(None) is None


class TestThunderGetTaskById:
    def test_get_task_by_id_found(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [{"id": "task-1", "name": "Task 1"}]
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client._get_task_by_id("task-1")
            assert result == {"id": "task-1", "name": "Task 1"}

    def test_get_task_by_id_not_found(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = []
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client._get_task_by_id("non-existent")
            assert result is None


class TestThunderGetFiles:
    def test_get_files_success(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [
            {
                "id": "task-1",
                "params": {"url": "magnet:test", "parent_folder_path": "/downloads"},
            }
        ]
        mock_pythunder.get_complete_tasks.return_value = []
        mock_pythunder.get_torrent_info.return_value = {
            "files": [
                {"file_index": 0, "name": "S01E01.mkv", "size_bytes": 1000000},
                {"file_index": 1, "name": "S01E02.mkv", "size_bytes": 1000000},
            ]
        }

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            files = client.get_files("task-1")
            assert files is not None
            assert len(files) == 2
            assert files[0]["id"] == 0
            assert files[0]["name"] == "S01E01.mkv"
            assert files[1]["id"] == 1
            assert files[1]["name"] == "S01E02.mkv"

    def test_get_files_no_task(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = []
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            files = client.get_files("task-1")
            assert files is None

    def test_get_files_no_url(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [
            {"id": "task-1", "params": {"parent_folder_path": "/downloads"}}
        ]
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            files = client.get_files("task-1")
            assert files is None

    def test_get_files_tid_none(self):
        mock_pythunder = MagicMock()

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            files = client.get_files(None)
            assert files is None


class TestThunderSetFileSelection:
    def test_set_file_selection_success(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [
            {
                "id": "task-1",
                "params": {"url": "magnet:test", "parent_folder_path": "/downloads"},
            }
        ]
        mock_pythunder.get_complete_tasks.return_value = []
        mock_pythunder._resolve_folder_id.return_value = "folder-1"
        mock_pythunder.download.return_value = {"id": "task-2"}
        mock_pythunder.delete_task.return_value = True

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.set_file_selection("task-1", {0: True, 1: False, 2: True})
            assert result is True
            assert client._recreated_tasks["task-1"] == "task-2"
            mock_pythunder.delete_task.assert_called_once_with("task-1", delete_files=False)
            mock_pythunder.download.assert_called_once()
            call_kwargs = mock_pythunder.download.call_args[1]
            assert call_kwargs["file_indices"] == "0,2"

    def test_set_file_selection_no_task(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = []
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.set_file_selection("task-1", {0: True})
            assert result is False

    def test_set_file_selection_nothing_selected(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [
            {
                "id": "task-1",
                "params": {"url": "magnet:test", "parent_folder_path": "/downloads"},
            }
        ]
        mock_pythunder.get_complete_tasks.return_value = []

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.set_file_selection("task-1", {0: False, 1: False})
            assert result is False

    def test_set_file_selection_recreate_failed(self):
        mock_pythunder = MagicMock()
        mock_pythunder.get_downloading_tasks.return_value = [
            {
                "id": "task-1",
                "params": {"url": "magnet:test", "parent_folder_path": "/downloads"},
            }
        ]
        mock_pythunder.get_complete_tasks.return_value = []
        mock_pythunder._resolve_folder_id.return_value = "folder-1"
        mock_pythunder.download.return_value = {}  # 无 id
        mock_pythunder.delete_task.return_value = True

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.set_file_selection("task-1", {0: True})
            assert result is False

    def test_set_file_selection_tid_none(self):
        mock_pythunder = MagicMock()

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.set_file_selection(None, {0: True})
            assert result is True


class TestThunderAddTorrentWithFileIndices:
    def test_add_torrent_with_file_indices(self):
        mock_pythunder = MagicMock()
        mock_pythunder._resolve_folder_id.return_value = "folder-1"
        mock_pythunder.download.return_value = {"id": "task-1"}

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.add_torrent_and_get_id(
                "magnet:test", download_dir="/downloads", file_indices="0,1,2", file_names="a.mkv,b.mkv"
            )
            assert result == "task-1"
            mock_pythunder.download.assert_called_once()
            call_kwargs = mock_pythunder.download.call_args[1]
            assert call_kwargs["file_indices"] == "0,1,2"
            assert call_kwargs["file_names"] == "a.mkv,b.mkv"

    def test_add_torrent_without_file_indices(self):
        mock_pythunder = MagicMock()
        mock_pythunder._resolve_folder_id.return_value = "folder-1"
        mock_pythunder.download.return_value = {"id": "task-1"}

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            result = client.add_torrent_and_get_id("magnet:test", download_dir="/downloads")
            assert result == "task-1"
            call_kwargs = mock_pythunder.download.call_args[1]
            assert call_kwargs.get("file_indices") is None
            assert call_kwargs.get("file_names") is None


class TestThunderOperationsWithResolvedTid:
    def test_start_torrents_resolves_tid(self):
        mock_pythunder = MagicMock()
        mock_pythunder.resume_task.return_value = True

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            client._recreated_tasks["old-task"] = "new-task"
            result = client.start_torrents("old-task")
            assert result is True
            mock_pythunder.resume_task.assert_called_once_with("new-task")

    def test_stop_torrents_resolves_tid(self):
        mock_pythunder = MagicMock()
        mock_pythunder.pause_task.return_value = True

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            client._recreated_tasks["old-task"] = "new-task"
            result = client.stop_torrents("old-task")
            assert result is True
            mock_pythunder.pause_task.assert_called_once_with("new-task")

    def test_delete_torrents_resolves_tid(self):
        mock_pythunder = MagicMock()
        mock_pythunder.delete_task.return_value = True

        with patch(_PY_THUNDER, return_value=mock_pythunder):
            client = Thunder(config={"host": "127.0.0.1", "port": "2345"})
            client._recreated_tasks["old-task"] = "new-task"
            result = client.delete_torrents(ids="old-task")
            assert result is True
            mock_pythunder.delete_task.assert_called_once_with("new-task", delete_files=False)
