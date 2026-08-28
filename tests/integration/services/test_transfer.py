"""Tests for app.services.transfer package."""

import re
import uuid
from unittest.mock import MagicMock, mock_open, patch

import pytest

from app.domain.enums import ProgressKey, SyncType
from app.domain.mediatypes import MediaType
from app.services.transfer.cleanup_service import TransferCleanupService
from app.services.transfer.existence_checker import MediaExistenceChecker
from app.services.transfer.filetransfer_service import FileTransferService
from app.services.transfer.history_manager import TransferHistoryManager
from app.services.transfer.path_resolver import TransferPathResolver


class TestTransferPathResolver:
    """Test suite for TransferPathResolver."""

    def test_get_format_dict_empty_media(self):
        resolver = TransferPathResolver()
        assert resolver.get_format_dict(None, MagicMock()) == {}

    def test_get_format_dict_populated(self):
        resolver = TransferPathResolver()
        media = MagicMock()
        media.title = "Test Movie"
        media.year = 2024
        media.org_string = "test.org"
        media.rev_string = "test.rev"
        media.original_title = "Original"
        media.get_name.return_value = "Test Movie"
        media.get_edtion_string.return_value = "Extended"
        media.resource_pix = "1080p"
        media.resource_team = "GROUP"
        media.customization = None
        media.resource_effect = None
        media.video_encode = "H264"
        media.audio_encode = "AAC"
        media.tmdb_id = 123
        media.imdb_id = "tt123"
        media.get_season_seq.return_value = 1
        media.get_episode_seqs.return_value = "01"
        media.get_season_item.return_value = "S01"
        media.get_episode_items.return_value = "E01"
        media.part = "Part1"

        media_service = MagicMock()
        media_service.get_episode_title.return_value = "Pilot"
        media_service.get_tmdb_en_title.return_value = "Test"

        fmt = resolver.get_format_dict(media, media_service)
        assert fmt["title"] == "Test Movie"
        assert fmt["year"] == 2024
        assert fmt["season"] == 1

    def test_get_movie_dest_path(self):
        resolver = TransferPathResolver(
            movie_dir_rmt_format="{title} ({year})",
            movie_file_rmt_format="{title} ({year})",
        )
        media = MagicMock()
        media.title = "Inception"
        media.year = 2010
        media.org_string = None
        media.rev_string = None
        media.original_title = None
        media.get_name.return_value = "Inception"
        media.get_edtion_string.return_value = None
        media.resource_pix = None
        media.resource_team = None
        media.customization = None
        media.resource_effect = None
        media.video_encode = None
        media.audio_encode = None
        media.tmdb_id = None
        media.imdb_id = None
        media.get_season_seq.return_value = None
        media.get_episode_seqs.return_value = None
        media.get_season_item.return_value = None
        media.get_episode_items.return_value = None
        media.part = None

        media_service = MagicMock()
        media_service.get_episode_title.return_value = None
        media_service.get_tmdb_en_title.return_value = None

        dir_name, file_name = resolver.get_movie_dest_path(media, media_service)
        assert "Inception" in dir_name
        assert "2010" in dir_name

    def test_get_tv_dest_path(self):
        resolver = TransferPathResolver(
            tv_dir_rmt_format="{title} ({year})",
            tv_season_rmt_format="Season {season}",
            tv_file_rmt_format="{title} - {season_episode}",
        )
        media = MagicMock()
        media.title = "Breaking Bad"
        media.year = 2008
        media.org_string = None
        media.rev_string = None
        media.original_title = None
        media.get_name.return_value = "Breaking Bad"
        media.get_edtion_string.return_value = None
        media.resource_pix = None
        media.resource_team = None
        media.customization = None
        media.resource_effect = None
        media.video_encode = None
        media.audio_encode = None
        media.tmdb_id = None
        media.imdb_id = None
        media.get_season_seq.return_value = 1
        media.get_episode_seqs.return_value = "01"
        media.get_season_item.return_value = "S01"
        media.get_episode_items.return_value = "E01"
        media.part = None

        media_service = MagicMock()
        media_service.get_episode_title.return_value = None
        media_service.get_tmdb_en_title.return_value = None

        dir_name, season_name, file_name = resolver.get_tv_dest_path(media, media_service)
        assert "Breaking Bad" in dir_name
        assert "Season" in season_name

    def test_get_best_target_path_single(self):
        resolver = TransferPathResolver(movie_path=["/movies"])
        assert resolver.get_best_target_path(MediaType.MOVIE) == "/movies"

    def test_get_best_target_path_by_commonpath(self):
        resolver = TransferPathResolver(
            movie_path=["/data/movies", "/backup/movies"],
        )
        result = resolver.get_best_target_path(MediaType.MOVIE, in_path="/data/downloads")
        assert result == "/data/movies"

    def test_is_target_dir_path(self):
        resolver = TransferPathResolver(
            movie_path=["/movies"],
            tv_path=["/tv"],
        )
        assert resolver.is_target_dir_path("/movies/Action") is True
        assert resolver.is_target_dir_path("/music") is False

    def test_get_best_unknown_path(self):
        resolver = TransferPathResolver(unknown_path=["/unknown1", "/unknown2"])
        # commonpath of "/data/downloads" and "/unknown1" is "/", which is in ["/", "\\"]
        # so the first match is returned
        assert resolver._get_best_unknown_path("/data/downloads") == "/unknown1"
        # commonpath of "/unknown1/sub" and "/unknown1" is "/unknown1", not in ["/", "\\"]
        assert resolver._get_best_unknown_path("/unknown1/sub") == "/unknown1"


class TestMediaExistenceChecker:
    """Test suite for MediaExistenceChecker."""

    def test_is_media_exists_movie_new(self):
        resolver = MagicMock()
        resolver.get_movie_dest_path.return_value = ("Inception (2010)", "Inception (2010)")
        resolver.movie_category_flag = False

        checker = MediaExistenceChecker(resolver)
        media = MagicMock()
        media.type = MediaType.MOVIE

        with patch("os.path.exists", return_value=False):
            dir_exist, dir_path, file_exist, file_path = checker.is_media_exists("/movies", media)

        assert dir_exist is False
        assert file_exist is False
        assert dir_path is not None
        assert "Inception (2010)" in dir_path

    def test_is_media_exists_movie_exists(self):
        resolver = MagicMock()
        resolver.get_movie_dest_path.return_value = ("Inception (2010)", "Inception (2010)")
        resolver.movie_category_flag = False

        checker = MediaExistenceChecker(resolver)
        media = MagicMock()
        media.type = MediaType.MOVIE

        with patch("os.path.exists", side_effect=lambda p: ".mp4" in p):
            dir_exist, dir_path, file_exist, file_path = checker.is_media_exists("/movies", media)

        assert dir_exist is False
        assert file_exist is True
        assert file_path is not None
        assert file_path.endswith(".mp4")

    def test_is_media_exists_tv_exists(self):
        resolver = MagicMock()
        resolver.get_tv_dest_path.return_value = ("Show (2020)", "Season 1", "Show - S01E01")
        resolver.tv_category_flag = False
        resolver.anime_category_flag = False

        checker = MediaExistenceChecker(resolver)
        media = MagicMock()
        media.type = MediaType.TV
        media.get_season_list.return_value = [1]
        media.get_episode_list.return_value = [1]

        with patch("os.path.exists", return_value=True):
            dir_exist, dir_path, file_exist, file_path = checker.is_media_exists("/tv", media)

        assert dir_exist is True
        assert dir_path is not None
        assert "Season 1" in dir_path

    def test_is_media_exists_tv_passes_media_service(self):
        """{en_title} / {episode_title} 依赖 media_service，必须透传给 path_resolver"""
        resolver = MagicMock()
        resolver.get_tv_dest_path.return_value = ("FBI (2018)", "Season 8", "FBI S08E07")
        resolver.tv_category_flag = False
        resolver.anime_category_flag = False

        media_service = MagicMock()
        checker = MediaExistenceChecker(resolver, media_service=media_service)
        media = MagicMock()
        media.type = MediaType.TV
        media.get_season_list.return_value = [8]
        media.get_episode_list.return_value = [7]

        with patch("os.path.exists", return_value=False):
            checker.is_media_exists("/tv", media)

        resolver.get_tv_dest_path.assert_called_once_with(media, media_service)

    def test_is_media_exists_movie_passes_media_service(self):
        resolver = MagicMock()
        resolver.get_movie_dest_path.return_value = ("Inception (2010)", "Inception (2010)")
        resolver.movie_category_flag = False

        media_service = MagicMock()
        checker = MediaExistenceChecker(resolver, media_service=media_service)
        media = MagicMock()
        media.type = MediaType.MOVIE

        with patch("os.path.exists", return_value=False):
            checker.is_media_exists("/movies", media)

        resolver.get_movie_dest_path.assert_called_once_with(media, media_service)

    def test_get_no_exists_medias_tv_passes_media_service(self):
        resolver = MagicMock()
        resolver.get_tv_dest_path.return_value = ("FBI (2018)", "Season 8", "")
        resolver.anime_category_flag = False
        resolver.tv_category_flag = False
        resolver.tv_path = []
        resolver.anime_path = []

        media_service = MagicMock()
        checker = MediaExistenceChecker(resolver, media_service=media_service)
        media = MagicMock()
        media.type = MediaType.TV

        checker.get_no_exists_medias(media, meta_info_fn=MagicMock(), season=8, total_num=1)

        resolver.get_tv_dest_path.assert_called_once_with(media, media_service)


class TestTransferHistoryManager:
    """Test suite for TransferHistoryManager."""

    def test_insert_transfer_history_delegates(self):
        mock_repo = MagicMock()
        manager = TransferHistoryManager(transfer_repo=mock_repo)
        manager.insert_transfer_history(
            in_from=SyncType.MAN,
            rmt_mode="copy",
            in_path="/src",
            out_path="/dst",
            dest="/dst",
            media_info=MagicMock(),
            dst_backend="local",
        )
        mock_repo.insert_transfer_history.assert_called_once()

    def test_delete_transfer_blacklist_delegates(self):
        mock_repo = MagicMock()
        manager = TransferHistoryManager(transfer_repo=mock_repo)
        manager.delete_transfer_blacklist("/path")
        mock_repo.delete_transfer_blacklist.assert_called_once_with(path="/path")

    def test_is_transfer_notin_blacklist_delegates(self):
        mock_repo = MagicMock()
        mock_repo.is_transfer_notin_blacklist.return_value = True
        manager = TransferHistoryManager(transfer_repo=mock_repo)
        result = manager.is_transfer_notin_blacklist("/path")
        assert result is True
        mock_repo.is_transfer_notin_blacklist.assert_called_once_with("/path")


class TestTransferCleanupService:
    """Test suite for TransferCleanupService."""

    def test_delete_media_file_local(self):
        history = MagicMock()
        resolver = MagicMock()
        cleanup = TransferCleanupService(
            history,
            resolver,
            media_service=MagicMock(),
            message=MagicMock(),
            event_bus=MagicMock(),
        )

        backend = MagicMock()
        backend.exists.return_value = True

        with patch.object(cleanup, "_resolve_backend_by_id", return_value=backend):
            cleanup.delete_media_file("/movies", "movie.mp4", "local")

        backend.remove.assert_called_once()

    def test_delete_media_file_not_found(self):
        from app.core.exceptions import ResourceNotFoundError

        history = MagicMock()
        resolver = MagicMock()
        cleanup = TransferCleanupService(
            history,
            resolver,
            media_service=MagicMock(),
            message=MagicMock(),
            event_bus=MagicMock(),
        )

        backend = MagicMock()
        backend.exists.return_value = False

        with patch.object(cleanup, "_resolve_backend_by_id", return_value=backend):
            with pytest.raises(ResourceNotFoundError):
                cleanup.delete_media_file("/movies", "movie.mp4", "local")

    def test_delete_history_del_source(self):
        history = MagicMock()
        transinfo = MagicMock()
        transinfo.SOURCE_PATH = "/src"
        transinfo.SOURCE_FILENAME = "file.mkv"
        transinfo.DEST_PATH = None
        transinfo.DEST_FILENAME = None
        transinfo.ID = 1
        history.get_transfer_info_by_id.return_value = transinfo

        resolver = MagicMock()
        cleanup = TransferCleanupService(
            history,
            resolver,
            media_service=MagicMock(),
            message=MagicMock(),
            event_bus=MagicMock(),
        )

        with patch.object(cleanup, "delete_media_file") as mock_delete:
            mock_delete.return_value = (True, "deleted")
            cleanup.delete_history([1], flag="del_source")

        history.delete_transfer_logs.assert_called_once_with([1])
        mock_delete.assert_called_once_with("/src", "file.mkv")


class TestFileTransferService:
    """Test suite for FileTransferService Facade."""

    @pytest.fixture
    def mock_service(self):
        """Build a FileTransferService with all dependencies mocked."""
        with (
            patch("app.services.transfer.filetransfer_service.TransferPathResolver") as mock_res_cls,
            patch("app.services.transfer.filetransfer_service.MediaExistenceChecker"),
            patch("app.services.transfer.filetransfer_service.TransferHistoryManager") as mock_hist_cls,
            patch("app.services.transfer.filetransfer_service.TransferCleanupService") as mock_cln_cls,
            patch("app.services.transfer.filetransfer_service.settings") as mock_settings,
            patch("app.services.transfer.filetransfer_service.get_lock_manager") as mock_get_lm,
        ):
            mock_settings.get.return_value = {}

            mock_lock = MagicMock()
            mock_lock.acquire.return_value = True
            mock_lock.__enter__.return_value = mock_lock
            mock_lock.__exit__.return_value = False
            mock_get_lm.return_value.create_lock.return_value = mock_lock

            mock_resolver = MagicMock()
            mock_resolver.unknown_path = []
            mock_res_cls.from_settings.return_value = mock_resolver

            mock_history = MagicMock()
            mock_hist_cls.return_value = mock_history

            mock_cleanup = MagicMock()
            mock_cln_cls.return_value = mock_cleanup

            mock_engine = MagicMock()

            service = FileTransferService(
                media_service=MagicMock(),
                message=MagicMock(),
                scraper=MagicMock(),
                thread_executor=MagicMock(),
                history_manager=mock_history,
                progress=MagicMock(),
                event_bus=MagicMock(),
                engine=mock_engine,
                path_resolver=mock_resolver,
                existence_checker=MagicMock(),
                cleanup_service=mock_cleanup,
                sync_path_repo=MagicMock(),
            )
            service._path_resolver = mock_resolver
            service._history = mock_history
            service._cleanup = mock_cleanup
            service._engine = mock_engine
            service.progress = MagicMock()
            service._event_bus = MagicMock()
            service.message = MagicMock()
            yield service

    def test_check_ignore_empty(self, mock_service):
        result, msg = mock_service.check_ignore([])
        assert result == []
        assert msg == ""

    def test_check_ignore_filtered(self, mock_service):
        mock_service._ignored_paths = re.compile(r"ignore")
        files = ["/path/ignore/file.mkv", "/path/ok/file.mkv"]
        result, msg = mock_service.check_ignore(files)
        assert len(result) == 1
        assert result[0] == "/path/ok/file.mkv"

    def test_check_ignore_all_filtered(self, mock_service):
        mock_service._ignored_paths = re.compile(r"ignore")
        files = ["/path/ignore/file.mkv"]
        result, msg = mock_service.check_ignore(files)
        assert result == []
        assert "没有新文件需要处理" in msg

    def test_discover_files_single_media_file(self, mock_service):
        with patch("os.path.isdir", return_value=False), patch("os.path.exists", return_value=True):
            bluray, files = mock_service._discover_files("/downloads/movie.mkv", None, (None, False), None)
        assert bluray is None
        assert files == ["/downloads/movie.mkv"]

    def test_discover_files_directory(self, mock_service):
        with (
            patch("os.path.isdir", return_value=True),
            patch("os.path.exists", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_dir_files",
                return_value=["/downloads/movie.mkv"],
            ),
        ):
            bluray, files = mock_service._discover_files("/downloads", None, (None, False), None)
        assert bluray is None
        assert files == ["/downloads/movie.mkv"]

    def test_discover_files_bluray(self, mock_service):
        with (
            patch("os.path.isdir", return_value=True),
            patch("os.path.exists", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value="/downloads/BDMV"
            ),
        ):
            bluray, files = mock_service._discover_files("/downloads", None, (None, False), None)
        assert bluray == "/downloads/BDMV"
        assert files == ["/downloads/BDMV"]

    def test_discover_files_invalid_extension(self, mock_service):
        with (
            patch("os.path.isdir", return_value=False),
            patch("os.path.exists", return_value=True),
        ):
            bluray, files = mock_service._discover_files("/downloads/readme.txt", None, (None, False), None)
        assert bluray is None
        assert files == []

    def test_finish_transfer(self, mock_service):
        result = mock_service._finish_transfer(True, "done")
        assert result == (True, "done")
        mock_service.progress.update.assert_called()
        mock_service.progress.end.assert_called_once_with(ProgressKey.FileTransfer)

    def test_transfer_post_process_with_alerts(self, mock_service):
        result = {
            "total_count": 2,
            "failed_count": 0,
            "alert_count": 1,
            "alert_messages": ["无法识别"],
            "message_medias": {},
            "success_flag": True,
            "error_message": "",
        }
        mock_service._transfer_post_process(result, SyncType.MAN, "/src", "copy", False)
        mock_service._event_bus.publish.assert_called()
        mock_service.message.send_transfer_fail_message.assert_called_once()

    def test_transfer_post_process_success_move_cleanup(self, mock_service):
        result = {
            "total_count": 1,
            "failed_count": 0,
            "alert_count": 0,
            "alert_messages": [],
            "message_medias": {},
            "success_flag": True,
            "error_message": "",
        }
        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_dir_files", return_value=[]),
            patch("app.services.transfer.filetransfer_service.shutil.rmtree") as mock_rmtree,
        ):
            mock_service._transfer_post_process(result, SyncType.MAN, "/src", "move", False)
        mock_rmtree.assert_called_once_with("/src")

    def test_transfer_post_process_success_no_cleanup(self, mock_service):
        result = {
            "total_count": 1,
            "failed_count": 0,
            "alert_count": 0,
            "alert_messages": [],
            "message_medias": {},
            "success_flag": True,
            "error_message": "",
        }
        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_dir_files", return_value=["file.mkv"]),
            patch("app.services.transfer.filetransfer_service.shutil.rmtree") as mock_rmtree,
        ):
            mock_service._transfer_post_process(result, SyncType.MAN, "/src", "move", False)
        mock_rmtree.assert_not_called()

    def test_link_sync_file(self, mock_service):
        mock_service._engine._execute.return_value = None
        with patch("os.path.exists", return_value=True), patch("os.makedirs"):
            result, msg = mock_service.link_sync_file("/src", "/src/file.mkv", "/dst", "copy")
        assert result == 0
        assert msg == ""
        mock_service._engine._execute.assert_called_once_with("/src/file.mkv", "/dst/file.mkv", "copy")

    def test_lookup_download_record(self, mock_service):
        download_info = MagicMock()
        download_info.TMDBID = 123
        download_info.TYPE = "movie"
        download_info.SE = "S01 E01"
        mock_service._history.download_repo.get_download_history_by_path.return_value = download_info
        mock_service.media.get_tmdb_info.return_value = {"id": 123}

        tmdb_info, media_type, dl_season, dl_episode = mock_service._lookup_download_record("/downloads/movie.mkv")
        assert tmdb_info == {"id": 123}
        assert media_type == MediaType.MOVIE
        assert dl_season == 1
        assert dl_episode == 1

    def test_lookup_download_record_no_se(self, mock_service):
        download_info = MagicMock()
        download_info.TMDBID = 123
        download_info.TYPE = "tv"
        download_info.SE = ""
        mock_service._history.download_repo.get_download_history_by_path.return_value = download_info
        mock_service.media.get_tmdb_info.return_value = {"id": 123}

        tmdb_info, media_type, dl_season, dl_episode = mock_service._lookup_download_record("/downloads/show.mkv")
        assert tmdb_info == {"id": 123}
        assert media_type == MediaType.TV
        assert dl_season is None
        assert dl_episode is None

    def test_lookup_download_record_not_found(self, mock_service):
        mock_service._history.download_repo.get_download_history_by_path.return_value = None
        tmdb_info, media_type, dl_season, dl_episode = mock_service._lookup_download_record("/downloads/movie.mkv")
        assert tmdb_info is None
        assert media_type is None
        assert dl_season is None
        assert dl_episode is None

    def test_get_sync_backend_by_dest(self, mock_service):
        entity = MagicMock()
        entity.dest = "/movies"
        entity.dst_backend = "smb_1"
        mock_service._sync_repo.get_all.return_value = [entity]
        result = mock_service.get_sync_backend_by_dest("/movies")
        assert result == "smb_1"

    def test_get_sync_backend_by_dest_no_match(self, mock_service):
        mock_service._sync_repo.get_all.return_value = []
        result = mock_service.get_sync_backend_by_dest("/movies")
        assert result == "local"

    def test_transfer_media_missing_path(self, mock_service):
        with patch("os.path.exists", return_value=False):
            status, msg = mock_service.transfer_media(SyncType.MAN, "/nonexistent")
        assert status is False
        assert "不存在" in msg

    def test_transfer_media_no_files(self, mock_service):
        unique_path = f"/empty/no-files-{uuid.uuid4().hex}"
        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_dir_files", return_value=[]),
        ):
            status, msg = mock_service.transfer_media(SyncType.MAN, unique_path)
        assert status is False  # bluray_disk_dir is None, empty file_list returns failure
        assert "未找到" in msg

    def test_transfer_media_fallback_episode_fills_begin_episode(self, mock_service):
        """文件名解析不出集号时，用订阅/下载历史的 fallback_episode 补齐 begin_episode"""
        unique_path = f"/dl/anime-{uuid.uuid4().hex}"
        media_file = f"{unique_path}/anime.mkv"
        media = MagicMock()
        media.type = MediaType.ANIME
        media.begin_season = 1
        media.begin_episode = None
        media.tmdb_info = {"id": 1}

        captured = {}

        def _fake_loop(medias, *args, **kwargs):
            captured["media"] = list(medias.values())[0]
            return {
                "total_count": 1,
                "failed_count": 0,
                "alert_count": 0,
                "alert_messages": [],
                "message_medias": {},
                "success_flag": True,
                "error_message": "",
            }

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_dir_files",
                return_value=[media_file],
            ),
            patch.object(mock_service.media, "get_media_info_on_files", return_value={media_file: media}),
            patch.object(mock_service, "_transfer_files_loop", side_effect=_fake_loop),
        ):
            status, msg = mock_service.transfer_media(
                SyncType.MAN,
                unique_path,
                operation="copy",
                tmdb_info={"id": 1},
                media_type="tv",
                season=1,
                fallback_episode=7,
            )
        assert status is True
        assert captured["media"].begin_episode == 7

    def test_transfer_media_fallback_not_override_existing_episode(self, mock_service):
        """文件名已解析出集号时不覆盖"""
        unique_path = f"/dl/anime-{uuid.uuid4().hex}"
        media_file = f"{unique_path}/anime.mkv"
        media = MagicMock()
        media.type = MediaType.ANIME
        media.begin_season = 1
        media.begin_episode = 6
        media.tmdb_info = {"id": 1}

        captured = {}

        def _fake_loop(medias, *args, **kwargs):
            captured["media"] = list(medias.values())[0]
            return {
                "total_count": 1,
                "failed_count": 0,
                "alert_count": 0,
                "alert_messages": [],
                "message_medias": {},
                "success_flag": True,
                "error_message": "",
            }

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_dir_files",
                return_value=[media_file],
            ),
            patch.object(mock_service.media, "get_media_info_on_files", return_value={media_file: media}),
            patch.object(mock_service, "_transfer_files_loop", side_effect=_fake_loop),
        ):
            status, msg = mock_service.transfer_media(
                SyncType.MAN,
                unique_path,
                operation="copy",
                tmdb_info={"id": 1},
                media_type="tv",
                season=1,
                fallback_episode=7,
            )
        assert status is True
        assert captured["media"].begin_episode == 6

    def test_transfer_media_fail_sets_success_flag_false(self, mock_service):
        """单个文件转移失败（_record_fail）时 transfer_media 必须返回失败，不能误报成功"""
        unique_path = f"/dl/anime-{uuid.uuid4().hex}"
        media_file = f"{unique_path}/anime.mkv"
        media = MagicMock()
        media.type = MediaType.ANIME
        media.begin_season = 1
        media.begin_episode = None
        media.tmdb_id = 1
        media.tmdb_info = {"id": 1}
        media.get_title_string.return_value = "Some Anime"

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_dir_files",
                return_value=[media_file],
            ),
            patch.object(mock_service.media, "get_media_info_on_files", return_value={media_file: media}),
            patch("os.path.getsize", return_value=1024),
            patch.object(
                mock_service,
                "_do_transfer_file",
                return_value=(1, 1, ["识别失败，无法从文件名中识别出集数"], 0, None, None, None),
            ),
        ):
            status, msg = mock_service.transfer_media(
                SyncType.MAN,
                unique_path,
                operation="copy",
                tmdb_info={"id": 1},
                media_type="tv",
                season=1,
            )
        assert status is False
        mock_service.message.send_transfer_fail_message.assert_called_once()

    def test_transfer_media_existing_file_success(self, mock_service):
        """目标文件已存在（exist_filenum>0）不视为失败，整体仍返回成功"""
        unique_path = f"/dl/anime-{uuid.uuid4().hex}"
        media_file = f"{unique_path}/anime.mkv"
        media = MagicMock()
        media.type = MediaType.ANIME
        media.begin_season = 1
        media.begin_episode = 6
        media.tmdb_id = 1
        media.tmdb_info = {"id": 1}
        media.get_title_string.return_value = "Some Anime"

        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch("app.services.transfer.filetransfer_service.PathUtils.is_invalid_path", return_value=False),
            patch("app.services.transfer.filetransfer_service.PathUtils.get_bluray_dir", return_value=None),
            patch(
                "app.services.transfer.filetransfer_service.PathUtils.get_dir_files",
                return_value=[media_file],
            ),
            patch.object(mock_service.media, "get_media_info_on_files", return_value={media_file: media}),
            patch("os.path.getsize", return_value=1024),
            patch.object(
                mock_service,
                "_do_transfer_file",
                return_value=(0, 0, [], 1, "/dst/anime.mkv", "/dst/anime.mkv", "/dst"),
            ),
        ):
            status, msg = mock_service.transfer_media(
                SyncType.MAN,
                unique_path,
                operation="copy",
                tmdb_info={"id": 1},
                media_type="tv",
                season=1,
            )
        assert status is True

    def test_record_fail(self, mock_service):
        mock_service._history.is_need_insert_transfer_unknown.return_value = True
        result = mock_service._record_fail("/file.mkv", "/file.mkv", "/dst", "copy", False, [], "识别失败")
        assert result[0] == 1
        assert result[1] == 1
        mock_service._history.insert_transfer_unknown.assert_called_once()


class TestTransferPathResolverMultiBackend:
    def _make_media(self):
        media = MagicMock()
        media.type = MediaType.TV
        media.category = "电视剧"
        media.title = "测试剧"
        media.year = 2026
        media.get_title_string.return_value = "测试剧"
        media.get_season_string.return_value = "Season 1"
        media.get_season_list.return_value = [1]
        return media

    def test_prefer_existing_local_path(self, tmp_path):
        dest_a = str(tmp_path / "tv_a")
        dest_b = str(tmp_path / "tv_b")
        resolver = TransferPathResolver(
            tv_path=[dest_a, dest_b],
            tv_backend=["local", "local"],
        )
        media = self._make_media()
        # mock 路径拼装：dest_b 下存在季目录
        resolver.get_dest_path_by_info = MagicMock(
            side_effect=lambda dest, m, ms: (
                f"{dest}/测试剧 (2026)/Season 1" if dest == dest_b else f"{dest}/测试剧 (2026)/Season 1"
            )
        )
        import pathlib

        pathlib.Path(f"{dest_b}/测试剧 (2026)/Season 1").mkdir(parents=True)
        result = resolver.get_best_target_path(
            MediaType.TV, in_path="/data/downloads", media=media, media_service=MagicMock()
        )
        assert result == dest_b

    def test_no_existing_falls_back_commonpath(self):
        resolver = TransferPathResolver(
            tv_path=["/tv1", "/tv2"],
            tv_backend=["local", "local"],
        )
        media = self._make_media()
        # 无已存在目录 → 走 commonpath（源路径在 /tv1 下）
        result = resolver.get_best_target_path(
            MediaType.TV, in_path="/tv1/downloads", media=media, media_service=MagicMock()
        )
        assert result == "/tv1"


class TestTransferReplicateToBackends:
    """多后端镜像复制测试."""

    def _make_service(self):
        with (
            patch("app.services.transfer.filetransfer_service.TransferPathResolver") as mock_res_cls,
            patch("app.services.transfer.filetransfer_service.get_lock_manager") as mock_get_lm,
        ):
            mock_lock = MagicMock()
            mock_lock.acquire.return_value = True
            mock_lock.__enter__.return_value = mock_lock
            mock_lock.__exit__.return_value = False
            mock_get_lm.return_value.create_lock.return_value = mock_lock

            mock_resolver = MagicMock()
            mock_resolver.unknown_path = []
            mock_res_cls.from_settings.return_value = mock_resolver

            service = FileTransferService(
                media_service=MagicMock(),
                message=MagicMock(),
                scraper=MagicMock(),
                thread_executor=MagicMock(),
                history_manager=MagicMock(),
                progress=MagicMock(),
                event_bus=MagicMock(),
                engine=MagicMock(),
                path_resolver=mock_resolver,
                existence_checker=MagicMock(),
                cleanup_service=MagicMock(),
                sync_path_repo=MagicMock(),
            )
            service._path_resolver = mock_resolver
            return service, mock_resolver

    def test_replicate_enqueues_other_backends(self):
        from app.services.transfer import filetransfer_service as module

        service, mock_resolver = self._make_service()
        backend_b = MagicMock()
        backend_b.id = "6"
        mock_resolver.list_enabled_dest_backends.return_value = [("/data/tv2", backend_b)]

        media = MagicMock()
        media.type = MediaType.TV

        mock_queue = MagicMock()
        with patch.object(module, "_get_mirror_queue", return_value=mock_queue):
            service._replicate_to_enabled_backends(media, "/data/tv1/测试剧 - S01E01.mkv", None)

        mock_queue.submit.assert_called_once()
        args = mock_queue.submit.call_args.args
        assert args[0] == service._mirror_upload
        assert args[4] == [("/data/tv2", backend_b)]
        assert args[5] == "测试剧 - S01E01.mkv"

    def test_replicate_skips_primary_backend(self):
        from app.services.transfer import filetransfer_service as module

        service, mock_resolver = self._make_service()
        primary = MagicMock()
        primary.id = "6"
        backend_b = MagicMock()
        backend_b.id = "6"
        mock_resolver.list_enabled_dest_backends.return_value = [("/data/tv2", backend_b)]

        media = MagicMock()
        media.type = MediaType.TV

        mock_queue = MagicMock()
        with patch.object(module, "_get_mirror_queue", return_value=mock_queue):
            service._replicate_to_enabled_backends(media, "/data/tv1/S01E01.mkv", primary)

        mock_queue.submit.assert_not_called()

    def test_mirror_upload_writes_and_skips_existing(self):
        service, mock_resolver = self._make_service()
        backend_b = MagicMock()
        backend_b.id = "6"
        backend_b.exists.return_value = False
        mock_resolver.get_dest_path_by_info.return_value = "/data/tv2/测试剧 (2026)/Season 1"

        media = MagicMock()
        media.type = MediaType.TV

        with patch("app.services.transfer.filetransfer_service.open", mock_open(read_data=b"data")):
            service._mirror_upload(media, "/data/tv1/S01E01.mkv", None, [("/data/tv2", backend_b)], "S01E01.mkv")

        backend_b.write_stream.assert_called_once()
        call_path = backend_b.write_stream.call_args[0][0]
        assert call_path == "/data/tv2/测试剧 (2026)/Season 1/S01E01.mkv"

    def test_mirror_upload_skip_existing_file(self):
        service, mock_resolver = self._make_service()
        backend_b = MagicMock()
        backend_b.id = "6"
        backend_b.exists.return_value = True
        mock_resolver.get_dest_path_by_info.return_value = "/data/tv2/测试剧 (2026)/Season 1"

        media = MagicMock()
        media.type = MediaType.TV

        service._mirror_upload(media, "/data/tv1/S01E01.mkv", None, [("/data/tv2", backend_b)], "S01E01.mkv")

        backend_b.write_stream.assert_not_called()
