"""下载器客户端 list_remote_dirs 单元测试."""

from unittest.mock import MagicMock, patch

from app.downloader.client._base import _IDownloadClient
from app.downloader.client.qbittorrent import Qbittorrent
from app.downloader.client_factory import DownloadClientFactory
from app.plugin_framework.builtin_plugins.dl_aria2.backend.download_client import Aria2
from app.schemas.download import Torrent


class _StubClient(_IDownloadClient):
    """最小可实例化的桩客户端"""

    client_id = "stub"
    client_type = "stub"
    client_name = "Stub"

    def __init__(self, dirs=None, torrents=None, dirs_error=None, torrents_error=None):
        self._dirs = dirs or []
        self._torrents = torrents or []
        self._dirs_error = dirs_error
        self._torrents_error = torrents_error

    def connect(self):
        return None

    def get_status(self):
        return True

    def get_torrents(self, ids=None, status=None, tag=None):
        if self._torrents_error:
            raise self._torrents_error
        return self._torrents, False

    def get_downloading_torrents(self, ids=None, tag=None):
        return []

    def get_completed_torrents(self, ids=None, tag=None):
        return []

    def get_files(self, tid=None):
        return []

    def set_torrents_status(self, ids, tags=None):
        return True

    def set_torrents_tag(self, ids=None, tags=None):
        return True

    def add_torrent(self, content, **kwargs):
        return True

    def start_torrents(self, ids=None):
        return True

    def stop_torrents(self, ids=None):
        return True

    def delete_torrents(self, delete_file=False, ids=None):
        return True

    def get_download_dirs(self):
        if self._dirs_error:
            raise self._dirs_error
        return self._dirs

    def change_torrent(self, tid=None, **kwargs):
        return True

    def set_speed_limit(self, download_limit=None, upload_limit=None):
        return True

    def recheck_torrents(self, ids=None):
        return True

    def get_free_space(self, path):
        return 0

    def _map_status(self, raw_state):
        return raw_state

    @property
    def _supported_statuses(self):
        return []


def _torrent(save_path):
    t = Torrent()
    t.save_path = save_path
    return t


class TestBaseListRemoteDirs:
    def test_combines_dirs_and_torrent_paths_deduped_sorted(self):
        client = _StubClient(
            dirs=["/downloads/complete", "/downloads"],
            torrents=[_torrent("/downloads"), _torrent("/mnt/incoming"), _torrent(None)],
        )
        assert client.list_remote_dirs() == ["/downloads", "/downloads/complete", "/mnt/incoming"]

    def test_tolerates_get_download_dirs_error(self):
        client = _StubClient(dirs_error=RuntimeError("boom"), torrents=[_torrent("/mnt/incoming")])
        assert client.list_remote_dirs() == ["/mnt/incoming"]

    def test_tolerates_get_torrents_error(self):
        client = _StubClient(dirs=["/downloads"], torrents_error=RuntimeError("boom"))
        assert client.list_remote_dirs() == ["/downloads"]

    def test_empty_when_no_sources(self):
        assert _StubClient().list_remote_dirs() == []


class TestQbittorrentListRemoteDirs:
    def test_includes_default_save_path(self):
        client = object.__new__(Qbittorrent)
        mock_qbc = MagicMock()
        client.qbc = mock_qbc
        mock_qbc.app_default_save_path.return_value = "/downloads/default"
        mock_qbc.torrents_categories.return_value = {
            "movies": {"savePath": "/downloads/movies"},
        }
        with patch.object(Qbittorrent, "get_torrents", return_value=([_torrent("/downloads/tv")], False)):
            dirs = client.list_remote_dirs()
        assert dirs == ["/downloads/default", "/downloads/movies", "/downloads/tv"]

    def test_without_connection_returns_torrent_paths_only(self):
        client = object.__new__(Qbittorrent)
        client.qbc = None
        with patch.object(Qbittorrent, "get_torrents", return_value=([_torrent("/downloads/tv")], False)):
            assert client.list_remote_dirs() == ["/downloads/tv"]


class TestAria2ListRemoteDirs:
    def test_returns_global_option_dir(self):
        client = object.__new__(Aria2)
        mock_rpc = MagicMock()
        client._client = mock_rpc
        mock_rpc.getGlobalOption.return_value = {"dir": "/mnt/aria2"}
        assert client.list_remote_dirs() == ["/mnt/aria2"]

    def test_returns_empty_without_client(self):
        client = object.__new__(Aria2)
        client._client = None
        assert client.list_remote_dirs() == []

    def test_returns_empty_when_dir_missing(self):
        client = object.__new__(Aria2)
        mock_rpc = MagicMock()
        client._client = mock_rpc
        mock_rpc.getGlobalOption.return_value = {}
        assert client.list_remote_dirs() == []


class TestClientFactoryGetRemoteDirs:
    def _make_factory(self):
        return DownloadClientFactory.__new__(DownloadClientFactory)

    def test_returns_empty_when_missing_params(self):
        factory = self._make_factory()
        assert factory.get_remote_dirs(dtype=None, config={}) == []
        assert factory.get_remote_dirs(dtype="qbittorrent", config=None) == []

    def test_returns_empty_when_client_build_failed(self):
        factory = self._make_factory()
        with patch.object(DownloadClientFactory, "_build_class", return_value=None):
            assert factory.get_remote_dirs(dtype="qbittorrent", config={"host": "h"}) == []

    def test_delegates_to_client(self):
        factory = self._make_factory()
        mock_client = MagicMock()
        mock_client.list_remote_dirs.return_value = ["/a", "/b"]
        with patch.object(DownloadClientFactory, "_build_class", return_value=mock_client) as build:
            result = factory.get_remote_dirs(dtype="qbittorrent", config={"host": "h"})
        build.assert_called_once_with(ctype="qbittorrent", conf={"host": "h"})
        assert result == ["/a", "/b"]
