"""qBittorrent 增量同步单元测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.downloader.client.qbittorrent import Qbittorrent


class TestQbittorrentSync:
    """测试 qBittorrent sync/maindata 增量逻辑."""

    @pytest.fixture
    def client(self):
        with patch.object(Qbittorrent, "connect"):
            with patch.object(Qbittorrent, "init_torrent_management"):
                with patch("qbittorrentapi.Client") as mock_qbc_cls:
                    mock_qbc = MagicMock()
                    mock_qbc_cls.return_value = mock_qbc
                    qb = Qbittorrent(
                        config={
                            "host": "127.0.0.1",
                            "port": "8080",
                            "username": "admin",
                            "password": "adminadmin",
                        }
                    )
                    qb.qbc = mock_qbc
                    qb.download_dir = [{"save_path": "/downloads", "container_path": "/downloads"}]
                    return qb, mock_qbc

    def test_get_torrents_uses_sync_for_completed(self, client):
        """获取已完成任务且无 ids 时使用 sync_maindata."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {
                    "name": "movie.mkv",
                    "state": "uploading",
                    "tags": "NEXUS_MEDIA",
                    "save_path": "/downloads",
                    "content_path": "/downloads/movie.mkv",
                    "total_size": 1000,
                    "progress": 1.0,
                    "dlspeed": 0,
                    "upspeed": 100,
                }
            },
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"
        assert torrents[0].labels == ["NEXUS_MEDIA"]
        assert qb._sync_rid == 1

    def test_get_torrents_sync_filter_by_tag(self, client):
        """sync 结果按标签过滤."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": True,
            "torrents": {
                "hash1": {"name": "a.mkv", "state": "uploading", "tags": "NEXUS_MEDIA"},
                "hash2": {"name": "b.mkv", "state": "uploading", "tags": "other"},
            },
        }

        torrents, error = qb.get_torrents(status="completed", tag="NEXUS_MEDIA")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"

    def test_get_torrents_sync_incremental_update(self, client):
        """增量更新合并到本地快照."""
        qb, mock_qbc = client
        qb._sync_torrents = {"hash1": {"name": "old.mkv", "state": "uploading", "tags": "NEXUS_MEDIA"}}
        qb._sync_rid = 1
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": False,
            "torrents": {"hash2": {"name": "new.mkv", "state": "uploading", "tags": "NEXUS_MEDIA"}},
            "torrents_removed": ["hash1"],
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash2"
        assert "hash1" not in qb._sync_torrents

    def test_get_torrents_sync_incremental_update_preserves_name(self, client):
        """增量更新未携带 name 时，保留本地快照中的 name."""
        qb, mock_qbc = client
        qb._sync_torrents = {"hash1": {"name": "movie.mkv", "state": "uploading", "tags": "NEXUS_MEDIA"}}
        qb._sync_rid = 1
        mock_qbc.sync_maindata.return_value = {
            "rid": 2,
            "full_update": False,
            "torrents": {"hash1": {"state": "uploading", "tags": "NEXUS_MEDIA,已整理"}},
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"
        assert torrents[0].name == "movie.mkv"
        assert torrents[0].labels == ["NEXUS_MEDIA", "已整理"]

    def test_get_torrents_sync_excludes_incomplete_states(self, client):
        """sync 结果排除非已完成状态."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {"name": "a.mkv", "state": "uploading", "tags": ""},
                "hash2": {"name": "b.mkv", "state": "downloading", "tags": ""},
            },
        }

        torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert torrents[0].id == "hash1"

    def test_get_torrents_sync_fallback_on_exception(self, client):
        """sync 失败时回退到 torrents_info."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.side_effect = Exception("sync error")
        mock_torrent = MagicMock()
        mock_torrent.hash = "hash1"
        mock_torrent.name = "movie.mkv"
        mock_torrent.size = 1000
        mock_torrent.state = "uploading"
        mock_torrent.tags = "NEXUS_MEDIA"
        mock_torrent.save_path = "/downloads"
        mock_torrent.content_path = "/downloads/movie.mkv"
        mock_torrent.progress = 1.0
        mock_torrent.dlspeed = 0
        mock_torrent.upspeed = 100
        mock_torrent.category = ""
        mock_torrent.tracker = ""
        mock_qbc.torrents_info.return_value = [mock_torrent]

        with patch.object(qb, "torrent_properties", return_value=MagicMock(id="hash1", labels=["NEXUS_MEDIA"])):
            torrents, error = qb.get_torrents(status="completed")

        assert not error
        assert len(torrents) == 1
        assert qb._sync_rid == 0

    def test_get_transfer_task_returns_paths(self, client):
        """get_transfer_task 返回标准化路径."""
        qb, mock_qbc = client
        mock_qbc.sync_maindata.return_value = {
            "rid": 1,
            "full_update": True,
            "torrents": {
                "hash1": {
                    "name": "movie.mkv",
                    "state": "uploading",
                    "tags": "NEXUS_MEDIA",
                    "save_path": "/downloads",
                    "content_path": "/downloads/movie.mkv",
                    "total_size": 1000,
                    "progress": 1.0,
                    "dlspeed": 0,
                    "upspeed": 100,
                }
            },
        }

        tasks = qb.get_transfer_task(tag="NEXUS_MEDIA")

        assert len(tasks) == 1
        assert tasks[0]["id"] == "hash1"
        assert tasks[0]["path"] == "/downloads/movie.mkv"


class TestQbittorrentAddTorrent:
    """qBittorrent 添加任务：传入下载目录时必须尊重该目录."""

    @pytest.fixture
    def client(self):
        with patch.object(Qbittorrent, "connect"):
            with patch.object(Qbittorrent, "init_torrent_management"):
                with patch("qbittorrentapi.Client") as mock_qbc_cls:
                    mock_qbc = MagicMock()
                    mock_qbc_cls.return_value = mock_qbc
                    qb = Qbittorrent(
                        config={
                            "host": "127.0.0.1",
                            "port": "8080",
                            "username": "admin",
                            "password": "adminadmin",
                            "torrent_management": "auto",
                        }
                    )
                    qb.qbc = mock_qbc
                    return qb, mock_qbc

    def test_add_torrent_honors_download_dir(self, client):
        """即使下载器配置了自动管理，传入 download_dir 也必须强制 is_auto=False 并透传 save_path."""
        qb, mock_qbc = client
        mock_qbc.torrents_add.return_value = "Ok."
        ret = qb.add_torrent(
            content=b"torrent-bytes",
            download_dir="/做种2",
        )
        assert ret is True
        _, kwargs = mock_qbc.torrents_add.call_args
        assert kwargs.get("save_path") == "/做种2"
        assert kwargs.get("use_auto_torrent_management") is False


class TestGetDownloadingTorrents:
    def test_get_downloading_excludes_completed(self):
        """已完成（progress=1，pausedUP 等）的任务不应计入正在下载数"""
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.schemas.download import Torrent, TorrentStatus
        

        downloading = Torrent()
        downloading.progress = 0.5
        downloading.status = TorrentStatus.Downloading
        completed_paused = Torrent()
        completed_paused.progress = 1.0
        completed_paused.status = TorrentStatus.Paused

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_torrents", return_value=([downloading, completed_paused], False)):
            result = qb.get_downloading_torrents()
        assert result is not None
        assert len(result) == 1
        assert result[0].progress == 0.5

    def test_get_downloading_returns_none_on_error(self):
        from app.downloader.client.qbittorrent import Qbittorrent

        qb = Qbittorrent.__new__(Qbittorrent)
        qb.qbc = MagicMock()
        with patch.object(Qbittorrent, "get_torrents", return_value=([], True)):
            assert qb.get_downloading_torrents() is None
