"""SyncService 单元测试."""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ValidationError
from app.domain.mediatypes import MediaType
from app.schemas.sync import ManualTransferResultDTO
from app.services.sync_service import SyncService


@pytest.fixture
def service():
    sync = MagicMock()
    filetransfer = MagicMock()
    media_cache = MagicMock()
    thread_executor = MagicMock()
    storage_repo = MagicMock()
    return SyncService(sync, filetransfer, media_cache, thread_executor, storage_repo)


class TestSyncServiceValidate:
    def test_validate_sync_path_root_source(self, service):
        with pytest.raises(ValidationError):
            service._validate_sync_path("/", "/dst", "copy")

    def test_validate_sync_path_subpath(self, service):
        with pytest.raises(ValidationError):
            service._validate_sync_path("/src", "/src/sub", "copy")

    def test_validate_sync_path_invalid_mode(self, service):
        with pytest.raises(ValidationError):
            service._validate_sync_path("/src", "/dst", "invalid")

    def test_validate_sync_path_ok(self, service):
        service._validate_sync_path("/src", "/dst", "copy")


class TestSyncServiceAddOrEdit:
    def test_add_new_path(self, service):
        service.add_or_edit_sync_path(
            sid=0,
            source="/src",
            dest="/dst",
            unknown="",
            mode="copy",
        )
        service._sync.insert_sync_path.assert_called_once()

    def test_edit_existing_path(self, service):
        service.add_or_edit_sync_path(
            sid=1,
            source="/src",
            dest="/dst",
            unknown="",
            mode="copy",
        )
        service._sync.delete_sync_path.assert_called_once_with(1)
        service._sync.insert_sync_path.assert_called_once()

    def test_check_sync_path_compatibility(self, service):
        service.check_sync_path(1, "compatibility", True)
        service._sync.check_sync_paths.assert_called_once_with(sid=1, compatibility=True)

    def test_check_sync_path_invalid_flag(self, service):
        with pytest.raises(ValidationError):
            service.check_sync_path(1, "unknown", True)


class TestSyncServiceTransfer:
    @patch("os.path.exists", return_value=False)
    def test_manual_transfer_path_not_exists(self, mock_exists, service):
        result = service.manual_transfer("/nonexistent", "copy")
        assert not result.success

    @patch("os.path.exists", return_value=True)
    @patch("os.path.normpath", side_effect=lambda x: x)
    def test_manual_transfer_submit(self, mock_norm, mock_exists, service):
        service._media_cache.get_tmdb_info.return_value = {"title": "Test"}
        service._filetransfer.get_sync_backend_by_dest.return_value = "local"
        result = service.manual_transfer(
            "/src/movie.mkv",
            "copy",
            outpath="/dst",
            media_type=MediaType.MOVIE,
            tmdbid=123,
        )
        assert result.success
        service._thread_executor.submit.assert_called_once()

    @patch("os.path.exists", return_value=True)
    @patch("os.path.normpath", side_effect=lambda x: x)
    def test_manual_transfer_no_tmdb(self, mock_norm, mock_exists, service):
        service._media_cache.get_tmdb_info.return_value = None
        result = service.manual_transfer("/src/movie.mkv", "copy", tmdbid=123)
        assert not result.success

    def test_build_media_type(self):
        assert SyncService.build_media_type("movie") == MediaType.MOVIE
        assert SyncService.build_media_type("tv") == MediaType.TV
        assert SyncService.build_media_type("unknown") == MediaType.UNKNOWN


class TestSyncServiceReIdentify:
    def _patch_lock_manager(self, acquired: bool):
        lock = MagicMock()
        lock.acquire.return_value = acquired
        manager = MagicMock()
        manager.create_lock.return_value = lock
        return patch("app.services.sync_service.get_lock_manager", return_value=manager)

    def test_re_identify_concurrent(self, service):
        from concurrent.futures import Future

        called = []

        def fake_submit(func, *args, **kwargs):
            called.append(args)
            future = Future()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
            return future

        service._thread_executor.submit.side_effect = fake_submit
        service._filetransfer.get_unknown_info_by_id.return_value = MagicMock(
            path="/src/movie.mkv", dest="/dst", mode="copy"
        )
        service._filetransfer.transfer_media.return_value = (True, "ok")

        with self._patch_lock_manager(True):
            result = service.re_identify_items("unidentification", [1, 2])
        assert result.success
        # 外层任务 + 内层并发任务都走同一 executor
        assert len(called) == 3  # _do_re_identify + 2 x _do_one

    def test_get_sub_path_concurrent(self, service):
        from concurrent.futures import Future

        called = []

        def fake_submit(func, *args, **kwargs):
            called.append(args)
            future = Future()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
            return future

        service._thread_executor.submit.side_effect = fake_submit
        with (
            patch("os.listdir", return_value=["dir1", "file1.mkv"]),
            patch("os.path.isdir", side_effect=lambda x: x.endswith("dir1")),
            patch("os.path.getsize", return_value=1024),
            patch("os.path.exists", return_value=True),
            patch("app.services.sync_service.StringUtils.str_filesize", return_value="1KB"),
        ):
            result = service.get_sub_path("/", ft="ALL")
        assert len(result) == 2
        assert len(called) == 2  # 两个条目并发处理

    def test_re_identify_submit(self, service):
        with self._patch_lock_manager(True):
            result = service.re_identify_items("unidentification", [1])
        assert result.success
        service._thread_executor.submit.assert_called_once()

    def test_re_identify_already_running(self, service):
        with self._patch_lock_manager(False):
            result = service.re_identify_items("unidentification", [1])
        assert not result.success


class TestSyncServiceQueries:
    def test_get_sync_paths_by_sid(self, service):
        service.get_sync_paths(sid="1")
        service._sync.get_sync_path_conf.assert_called_once_with("1")

    def test_get_sync_paths_all(self, service):
        service.get_sync_paths()
        service._sync.get_all_sync_path_conf.assert_called_once()

    def test_transfer_sync(self, service):
        service.transfer_sync(sid="1")
        service._sync.transfer_sync.assert_called_once_with(sid="1")

    def test_get_sub_path_root(self, service):
        from concurrent.futures import Future

        def fake_submit(func, *args, **kwargs):
            future = Future()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
            return future

        service._thread_executor.submit.side_effect = fake_submit
        with (
            patch("os.listdir", return_value=["dir1", "file1.mkv"]),
            patch("os.path.isdir", side_effect=lambda x: x.endswith("dir1")),
            patch("os.path.getsize", return_value=1024),
            patch("os.path.exists", return_value=True),
            patch("app.services.sync_service.StringUtils.str_filesize", return_value="1KB"),
        ):
            result = service.get_sub_path("/", ft="ALL")
        assert len(result) == 2


class TestSyncServiceStatic:
    @patch("shutil.move")
    def test_rename_file_success(self, mock_move):
        result = SyncService.rename_file("/a/old.mkv", "new.mkv")
        assert result.success

    @patch("shutil.move", side_effect=OSError("fail"))
    def test_rename_file_failure(self, mock_move):
        result = SyncService.rename_file("/a/old.mkv", "new.mkv")
        assert not result.success

    def test_rename_file_empty(self):
        assert SyncService.rename_file("", "").success

    def test_exec_test_command_invalid_format(self):
        assert SyncService.exec_test_command("bad") is None

    def test_exec_test_command_unknown_object(self):
        assert SyncService.exec_test_command("Unknown().foo()") is None

    @patch("importlib.import_module")
    def test_exec_test_command_known_object(self, mock_import):
        obj = MagicMock()
        obj.test_method.return_value = True
        cls = MagicMock(return_value=obj)
        mock_import.return_value.Config = cls
        result = SyncService.exec_test_command("Config().test_method()")
        assert result is True

    def test_test_connection_empty(self):
        result = SyncService.test_connection("")
        assert result.success

    @patch("app.services.sync_service.SyncService.exec_test_command", return_value=True)
    def test_test_connection_single(self, mock_exec):
        result = SyncService.test_connection("Config().test_method()")
        assert result.success

    @patch("importlib.import_module")
    def test_test_connection_pipe(self, mock_import):
        obj = MagicMock()
        obj.get_status.return_value = True
        cls = MagicMock(return_value=obj)
        module = MagicMock()
        module.MyClass = cls
        mock_import.return_value = module
        result = SyncService.test_connection("mymodule|MyClass")
        assert result.success

    def test_update_directory(self, monkeypatch):
        mock_settings = MagicMock()
        mock_settings.get.return_value = {"key": "old"}
        monkeypatch.setattr("app.services.sync_service.settings", mock_settings)
        monkeypatch.setattr(
            "app.services.sync_service.set_config_directory",
            lambda cfg, oper, key, value, replace_value: {"key": value},
        )
        result = SyncService.update_directory("add", "key", "/path")
        assert result.success
        mock_settings.save.assert_called_once_with({"key": "/path"})


class TestSyncServiceRemoteSource:
    def _make_backend(self):
        backend = MagicMock()
        backend.exists.return_value = True
        return backend

    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_remote_path_exists_true(self, mock_resolve, service):
        backend = self._make_backend()
        mock_resolve.return_value = backend
        assert service.remote_path_exists("/vol2/media/tv/重器", "5") is True
        backend.exists.assert_called_once_with("/vol2/media/tv/重器")

    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_remote_path_exists_backend_missing(self, mock_resolve, service):
        mock_resolve.return_value = None
        assert service.remote_path_exists("/x", "5") is False

    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_remote_path_exists_not_found(self, mock_resolve, service):
        backend = self._make_backend()
        backend.exists.return_value = False
        mock_resolve.return_value = backend
        assert service.remote_path_exists("/missing", "5") is False

    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_stage_remote_file(self, mock_resolve, service):
        import io

        backend = self._make_backend()
        file_info = MagicMock()
        file_info.is_dir = False
        backend.stat.return_value = file_info
        backend.read_stream.return_value = io.BytesIO(b"media-bytes")
        mock_resolve.return_value = backend
        local = service._stage_remote_source("/remote/movie.mkv", "5")
        assert local
        assert os.path.exists(local)
        with open(local, "rb") as f:
            assert f.read() == b"media-bytes"
        backend.read_stream.assert_called_once_with("/remote/movie.mkv")

    @patch("app.services.sync_service.SyncService._stage_remote_dir")
    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_stage_remote_dir(self, mock_resolve, mock_stage_dir, service):
        backend = self._make_backend()
        dir_info = MagicMock()
        dir_info.is_dir = True
        backend.stat.return_value = dir_info
        mock_resolve.return_value = backend
        local = service._stage_remote_source("/remote/tv", "5")
        assert local
        mock_stage_dir.assert_called_once()

    @patch("app.services.sync_service.SyncService._resolve_backend")
    def test_stage_remote_missing(self, mock_resolve, service):
        backend = self._make_backend()
        backend.exists.return_value = False
        mock_resolve.return_value = backend
        assert service._stage_remote_source("/missing", "5") == ""


class TestSyncServiceSameBackend:
    def test_same_backend_no_staging(self, service):
        """同后端转移：不暂存，直接提交 src_backend"""
        src_backend = MagicMock()
        src_backend.id = "5"
        src_backend.exists.return_value = True
        dst_backend = MagicMock()
        dst_backend.id = "5"
        service._resolve_backend = MagicMock(return_value=src_backend)
        service._resolve_dst_backend_by_dest = MagicMock(return_value=dst_backend)
        service._stage_remote_source = MagicMock(return_value="/tmp/staged")
        service._submit_manual_transfer = MagicMock(return_value=ManualTransferResultDTO(success=True, message="ok"))

        result = service.manual_transfer(inpath="/remote/tv/剧", syncmod="copy", src_backend_id="5")

        assert result.success
        service._stage_remote_source.assert_not_called()
        call_args = service._submit_manual_transfer.call_args
        assert call_args.kwargs["src_backend"] is src_backend
        assert call_args.args[8] is dst_backend

    def test_cross_backend_stages(self, service):
        """跨后端远程源：暂存到本地"""
        src_backend = MagicMock()
        src_backend.id = "5"
        src_backend.exists.return_value = True
        dst_backend = MagicMock()
        dst_backend.id = "6"
        service._resolve_backend = MagicMock(return_value=src_backend)
        service._resolve_dst_backend_by_dest = MagicMock(return_value=dst_backend)
        service._stage_remote_source = MagicMock(return_value="/tmp/staged")

        result = service.manual_transfer(inpath="/remote/tv/剧", syncmod="copy", src_backend_id="5")

        service._stage_remote_source.assert_called_once()
        assert result.success


class TestSyncServiceDstBackendId:
    def test_explicit_dst_backend_id_used(self, service):
        """显式指定 dst_backend_id 时优先使用，不再查 sync path"""
        from app.storage.backends.base import StorageConfig, StorageType

        service._filetransfer.get_sync_backend_by_dest = MagicMock(return_value="local")
        backend = MagicMock()
        backend.id = "7"
        service._storage_backend_repo = MagicMock()
        entity = MagicMock()
        entity.id = 7
        entity.name = "s3"
        entity.type = "s3"
        entity.enabled = True
        entity.config = {}
        service._storage_backend_repo.get_by_id.return_value = entity

        with (
            patch(
                "app.services.sync_service.StorageBackendFactory.get_config_info",
                return_value=(StorageType.S3, StorageConfig),
            ),
            patch("app.services.sync_service.StorageBackendFactory.create", return_value=backend),
        ):
            result = service._resolve_dst_backend_by_dest("/data/media", "7")

        assert result is backend
        service._filetransfer.get_sync_backend_by_dest.assert_not_called()
