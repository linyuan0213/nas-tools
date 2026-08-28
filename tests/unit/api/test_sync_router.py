"""Sync API Router 单元测试."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import (
    get_current_user,
    get_filetransfer_service,
    get_sync_service,
    get_thread_executor,
)
from api.routers import sync as sync_router
from app.schemas.auth import UserContext


class _MockResult:
    def __init__(self, success=True, message="ok"):
        self.success = success
        self.message = message


@pytest.fixture
def mock_sync_service():
    svc = MagicMock()
    svc.add_or_edit_sync_path.return_value = None
    svc.check_sync_path.return_value = None
    svc.delete_sync_path.return_value = None
    svc.get_sub_path.return_value = []
    svc.get_transfer_info_by_id.return_value = None
    svc.get_unknown_info_by_id.return_value = None
    svc.manual_transfer.return_value = _MockResult()
    svc.rename_file.return_value = _MockResult()
    svc.test_connection.return_value = _MockResult()
    svc.update_directory.return_value = _MockResult()
    svc.re_identify_items.return_value = _MockResult()
    svc.get_sync_paths.return_value = {}
    svc.build_media_type.return_value = "movie"
    return svc


@pytest.fixture
def mock_filetransfer_service():
    ft = MagicMock()
    ft.delete_transfer_unknown.return_value = 0
    ft.delete_transfer_unknowns.return_value = None
    ft.delete_media_file.return_value = None
    ft.delete_history.return_value = None
    ft.update_transfer_unknown_state.return_value = None
    return ft


@pytest.fixture
def client(mock_sync_service, mock_filetransfer_service):
    app = FastAPI()
    app.include_router(sync_router.router, prefix="/api/v1/sync")
    admin_ctx = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["setting:view", "setting:update", "subscription:view", "subscription:manage"],
    )
    app.dependency_overrides[get_current_user] = lambda: admin_ctx
    app.dependency_overrides[get_sync_service] = lambda: mock_sync_service
    app.dependency_overrides[get_filetransfer_service] = lambda: mock_filetransfer_service
    app.dependency_overrides[get_thread_executor] = lambda: MagicMock()
    with TestClient(app) as c:
        yield c


class TestSyncRouter:
    def test_add_or_edit_sync_path(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/paths/save", json={"source": "/src", "dest": "/dst"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_sync_service.add_or_edit_sync_path.assert_called_once()

    def test_check_sync_path(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/paths/check", json={"sid": 1, "flag": "test", "checked": True})
        assert resp.status_code == 200
        mock_sync_service.check_sync_path.assert_called_once()

    def test_del_unknown_path_list(self, client, mock_filetransfer_service):
        resp = client.post("/api/v1/sync/unknown/delete", json={"id": [1, 2, 3]})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_filetransfer_service.delete_transfer_unknowns.assert_called_once_with([1, 2, 3])

    def test_del_unknown_path_single(self, client, mock_filetransfer_service):
        mock_filetransfer_service.delete_transfer_unknown.return_value = 0
        resp = client.post("/api/v1/sync/unknown/delete", json={"id": 1})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_del_unknown_path_single_failed(self, client, mock_filetransfer_service):
        mock_filetransfer_service.delete_transfer_unknown.return_value = 1
        resp = client.post("/api/v1/sync/unknown/delete", json={"id": 1})
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_delete_files(self, client, mock_filetransfer_service):
        resp = client.post("/api/v1/sync/files/delete", json={"files": ["/a/b.mkv"], "backend_id": "local"})
        assert resp.status_code == 200
        mock_filetransfer_service.delete_media_file.assert_called_once()

    def test_delete_sync_path(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/paths/delete", json={"id": 1})
        assert resp.status_code == 200
        mock_sync_service.delete_sync_path.assert_called_once_with(1)

    def test_get_sub_path(self, client, mock_sync_service):
        mock_sync_service.get_sub_path.return_value = ["dir1", "dir2"]
        resp = client.post("/api/v1/sync/paths/sub", json={"directory": "/src"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["count"] == 2

    def test_rename_no_logid_or_unknown_id(self, client):
        resp = client.post("/api/v1/sync/rename", json={})
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_rename_success(self, client, mock_sync_service):
        trans = MagicMock()
        trans.SOURCE_PATH = "/src"
        trans.SOURCE_FILENAME = "movie.mkv"
        trans.DEST = "/dst"
        mock_sync_service.get_transfer_info_by_id.return_value = trans
        resp = client.post("/api/v1/sync/rename", json={"logid": 1, "syncmod": "link"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_rename_file(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/rename/file", json={"path": "/a", "name": "b"})
        assert resp.status_code == 200
        mock_sync_service.rename_file.assert_called_once_with(path="/a", name="b")

    def test_rename_udf_path_not_exists(self, client):
        resp = client.post("/api/v1/sync/rename/udf", json={"inpath": "/nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_rename_udf_remote_path_not_exists(self, client, mock_sync_service):
        mock_sync_service.remote_path_exists.return_value = False
        resp = client.post(
            "/api/v1/sync/rename/udf",
            json={"inpath": "/vol2/media/tv/重器", "src_backend_id": "5"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] != 0
        mock_sync_service.remote_path_exists.assert_called_once_with("/vol2/media/tv/重器", "5")

    def test_rename_udf_remote_path_ok(self, client, mock_sync_service):
        mock_sync_service.remote_path_exists.return_value = True
        resp = client.post(
            "/api/v1/sync/rename/udf",
            json={"inpath": "/vol2/media/tv/重器", "syncmod": "copy", "src_backend_id": "5"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_sync_service.manual_transfer.assert_called_once()
        call_kwargs = mock_sync_service.manual_transfer.call_args.kwargs
        assert call_kwargs["inpath"] == "/vol2/media/tv/重器"
        assert call_kwargs["src_backend_id"] == "5"

    def test_run_directory_sync(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/run", json={"sid": 1})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_test_connection(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/paths/test_connection", json={"command": "test"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_update_directory(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/directories/update", json={"oper": "add", "key": "k", "value": "v"})
        assert resp.status_code == 200
        mock_sync_service.update_directory.assert_called_once()

    def test_delete_history(self, client, mock_filetransfer_service):
        resp = client.post("/api/v1/sync/history/delete", json={"logids": [1, 2]})
        assert resp.status_code == 200
        mock_filetransfer_service.delete_history.assert_called_once_with(logids=[1, 2], flag=None)

    def test_get_sync_path(self, client, mock_sync_service):
        mock_sync_service.get_sync_paths.return_value = {"id": 1}
        resp = client.post("/api/v1/sync/paths", json={"sid": 1})
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 1

    def test_re_identification(self, client, mock_sync_service):
        resp = client.post("/api/v1/sync/reidentify", json={"flag": "unidentification", "ids": [1]})
        assert resp.status_code == 200
        mock_sync_service.re_identify_items.assert_called_once_with(flag="unidentification", ids=[1])
