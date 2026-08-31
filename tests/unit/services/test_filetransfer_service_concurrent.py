"""FileTransferService 并发转移单元测试."""

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from app.services.transfer.filetransfer_service import FileTransferService


@pytest.fixture
def service():
    svc = FileTransferService(
        media_service=MagicMock(),
        message=MagicMock(),
        scrape_queue_service=MagicMock(),
        thread_executor=MagicMock(),
        history_manager=MagicMock(),
        progress=MagicMock(),
        event_bus=MagicMock(),
        engine=MagicMock(),
        sync_path_repo=MagicMock(),
        path_resolver=MagicMock(),
        existence_checker=MagicMock(),
        cleanup_service=MagicMock(),
    )
    return svc


class TestFileTransferServiceConcurrent:
    def test_merge_transfer_results(self, service):
        r1 = {
            "total_count": 2,
            "failed_count": 0,
            "alert_count": 0,
            "alert_messages": [],
            "message_medias": {"k1": "v1"},
            "success_flag": True,
            "error_message": "",
            "exist_filenum": 1,
        }
        r2 = {
            "total_count": 1,
            "failed_count": 1,
            "alert_count": 1,
            "alert_messages": ["err"],
            "message_medias": {"k2": "v2"},
            "success_flag": False,
            "error_message": "err",
            "exist_filenum": 0,
        }
        merged = service._merge_transfer_results([r1, r2])
        assert merged["total_count"] == 3
        assert merged["failed_count"] == 1
        assert merged["success_flag"] is False
        assert merged["message_medias"] == {"k1": "v1", "k2": "v2"}
        assert merged["alert_messages"] == ["err"]

    def test_run_parallel_with_executor(self, service):
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
        results = service._run_parallel([1, 2], lambda x: x * 2)
        assert results == [2, 4]
        assert len(called) == 2

    def test_run_parallel_without_executor(self, service):
        service._thread_executor = None
        results = service._run_parallel([1, 2], lambda x: x * 2)
        assert results == [2, 4]

    def test_run_parallel_isolates_exceptions(self, service):
        def fake_submit(func, *args, **kwargs):
            future = Future()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                future.set_exception(e)
            else:
                future.set_result(result)
            return future

        def _maybe_fail(x):
            if x == 1:
                raise RuntimeError("fail")
            return x * 2

        service._thread_executor.submit.side_effect = fake_submit
        results = service._run_parallel([1, 2], _maybe_fail)
        assert results[0] is None
        assert results[1] == 4

    def test_transfer_files_groups_by_dist_path(self, service):
        from concurrent.futures import Future

        media1 = MagicMock()
        media1.type = "movie"
        media2 = MagicMock()
        media2.type = "tv"
        medias = {"/src/a.mkv": media1, "/src/b.mkv": media2}

        service._path_resolver.get_best_target_path.side_effect = (
            lambda mtype, in_path, size, media=None, media_service=None: f"/dst/{mtype}"
        )

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
        with patch.object(
            service,
            "_transfer_files_loop",
            return_value={
                "total_count": 1,
                "failed_count": 0,
                "alert_count": 0,
                "alert_messages": [],
                "message_medias": {},
                "success_flag": True,
                "error_message": "",
                "exist_filenum": 0,
            },
        ) as mock_loop:
            service._transfer_files(medias, "WEB", "/src", "copy", None, None, None, (None, False), False, None, None)
            assert mock_loop.call_count == 2

    def test_transfer_files_bluray_falls_back_to_serial(self, service):
        media1 = MagicMock()
        medias = {"/src/a.mkv": media1}
        service._thread_executor = None
        with patch.object(
            service,
            "_transfer_files_loop",
            return_value={
                "total_count": 1,
                "failed_count": 0,
                "alert_count": 0,
                "alert_messages": [],
                "message_medias": {},
                "success_flag": True,
                "error_message": "",
                "exist_filenum": 0,
            },
        ) as mock_loop:
            service._transfer_files(
                medias, "WEB", "/src", "copy", None, None, "/src/bluray", (None, False), False, None, None
            )
            assert mock_loop.call_count == 1
