"""事件处理器单元测试."""

from unittest.mock import MagicMock, patch

from app.events import Event
from app.events.constants import (
    DOWNLOAD_COMPLETED,
    MEDIA_EPISODE_TRANSFERRED,
    MEDIA_TRANSFER_FINISHED,
    SUBSCRIBE_FINISHED,
    TRANSFER_FAIL,
)


class TestTransferHandlers:
    """Test suite for transfer handlers."""

    def test_handle_media_transfer_finished(self):
        from app.services.transfer.handlers import handle_media_transfer_finished

        event = Event(
            event_type=MEDIA_TRANSFER_FINISHED,
            payload={
                "in_path": "/dl",
                "file": "movie.mkv",
                "target_path": "/media",
                "dest": "/media/Movie (2024)/movie.mkv",
                "media_info": {"title": "Movie"},
            },
        )
        # Should not raise
        handle_media_transfer_finished(event)

    def test_handle_transfer_fail(self):
        from app.services.transfer.handlers import handle_transfer_fail

        event = Event(
            event_type=TRANSFER_FAIL,
            payload={"path": "/dl/movie.mkv", "count": 1, "reason": "test"},
        )
        # Should not raise
        handle_transfer_fail(event)

    def test_handle_download_completed_success(self):
        from app.services.transfer.handlers import handle_download_completed

        mock_pipeline = MagicMock()
        mock_pipeline.process.return_value = (True, "ok")

        mock_client = MagicMock()
        mock_factory = MagicMock()
        mock_factory.get_downloader_conf.return_value = {
            "name": "QB",
            "rmt_mode": "link",
        }
        mock_factory.get_client.return_value = mock_client

        event = Event(
            event_type=DOWNLOAD_COMPLETED,
            payload={
                "downloader_id": "qb1",
                "task_id": "task1",
                "path": "/dl/movie.mkv",
                "tags": ["NEXUS_MEDIA"],
                "name": "movie",
            },
        )
        handle_download_completed(event, download_client_factory=mock_factory, transfer_pipeline=mock_pipeline)

        mock_pipeline.process.assert_called_once()

    def test_handle_download_completed_no_conf(self):
        from app.services.transfer.handlers import handle_download_completed

        mock_factory = MagicMock()
        mock_factory.get_downloader_conf.return_value = None

        event = Event(
            event_type=DOWNLOAD_COMPLETED,
            payload={
                "downloader_id": "qb1",
                "task_id": "task1",
                "path": "/dl/movie.mkv",
            },
        )
        handle_download_completed(event, download_client_factory=mock_factory)


class TestSubscribeHandlers:
    """Test suite for subscribe handlers."""

    def test_handle_subscribe_finished(self):
        from app.services.subscribe.handlers import handle_subscribe_finished

        event = Event(
            event_type=SUBSCRIBE_FINISHED,
            payload={"media_info": {"title": "Test"}, "rssid": 1},
        )
        # Should not raise
        handle_subscribe_finished(event)

    def test_handle_media_episode_transferred_no_subscribe(self):
        from app.services.subscribe.handlers import handle_media_episode_transferred

        mock_repo = MagicMock()
        mock_repo.get_id.return_value = None

        with patch("app.services.subscribe.handlers.SubscribeTvRepositoryAdapter", return_value=mock_repo):
            event = Event(
                event_type=MEDIA_EPISODE_TRANSFERRED,
                payload={
                    "tmdb_id": "123",
                    "title": "Test TV",
                    "season": "1",
                    "episodes": [1, 2],
                    "total_episodes": 10,
                },
            )
            handle_media_episode_transferred(event)

        mock_repo.get_id.assert_called_once_with(title="Test TV", season="1", tmdbid="123")
        mock_repo.update_lack.assert_not_called()

    def test_handle_media_episode_transferred_with_lack(self):
        from app.services.subscribe.handlers import handle_media_episode_transferred

        mock_repo = MagicMock()
        mock_repo.get_id.return_value = 42
        mock_ep_repo = MagicMock()
        # 订阅当前缺失 1-10
        mock_ep_repo.get.return_value = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        with (
            patch("app.services.subscribe.handlers.SubscribeTvRepositoryAdapter", return_value=mock_repo),
            patch("app.services.subscribe.handlers.SubscribeTvEpisodeRepositoryAdapter", return_value=mock_ep_repo),
        ):
            event = Event(
                event_type=MEDIA_EPISODE_TRANSFERRED,
                payload={
                    "tmdb_id": "123",
                    "title": "Test TV",
                    "season": "1",
                    "episodes": [1, 2, 3],
                    "total_episodes": 10,
                },
            )
            handle_media_episode_transferred(event)

        mock_repo.update_state.assert_called_once()
        mock_repo.update_lack.assert_called_once()
        call_args = mock_repo.update_lack.call_args[1]
        assert call_args["rssid"] == 42
        assert call_args["lack_episodes"] == [4, 5, 6, 7, 8, 9, 10]

    def test_handle_media_episode_transferred_all_done(self):
        from app.services.subscribe.handlers import handle_media_episode_transferred

        mock_repo = MagicMock()
        mock_repo.get_id.return_value = 42
        mock_ep_repo = MagicMock()
        mock_ep_repo.get.return_value = [1, 2, 3, 4, 5]

        with (
            patch("app.services.subscribe.handlers.SubscribeTvRepositoryAdapter", return_value=mock_repo),
            patch("app.services.subscribe.handlers.SubscribeTvEpisodeRepositoryAdapter", return_value=mock_ep_repo),
        ):
            event = Event(
                event_type=MEDIA_EPISODE_TRANSFERRED,
                payload={
                    "tmdb_id": "123",
                    "title": "Test TV",
                    "season": "1",
                    "episodes": [1, 2, 3, 4, 5],
                    "total_episodes": 5,
                },
            )
            handle_media_episode_transferred(event)

        mock_repo.update_state.assert_called_with(title=None, year=None, season=None, rssid=42, state="C")
        # 完成时不再调用 update_lack（避免写入空串导致后续 int("") 崩溃）
        mock_repo.update_lack.assert_not_called()
