"""Download API Router 单元测试."""

import queue
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user, get_downloader_service
from api.exception_handlers import register_exception_handlers
from api.routers import download as download_router
from app.schemas.auth import UserContext


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(download_router.router, prefix="/api/download")
    user_ctx = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["download:view", "download:manage"],
    )
    app.dependency_overrides[get_current_user] = lambda: user_ctx
    with TestClient(app) as c:
        yield c


class TestDownloadEventsGenerator:
    def test_yields_event_data(self):
        from api.routers.download import _event_stream_generator

        q = queue.Queue()
        q.put({"event": "download.started", "data": {"title": "Test"}})

        gen = _event_stream_generator(q)
        line = next(gen)
        assert "event: download.started" in line
        assert "Test" in line

    def test_yields_keepalive_on_empty(self):
        from api.routers.download import _event_stream_generator

        mq = MagicMock()
        mq.get.side_effect = queue.Empty

        gen = _event_stream_generator(mq)
        line = next(gen)
        assert line == ": keepalive\n\n"

    def test_loops_after_keepalive(self):
        from api.routers.download import _event_stream_generator

        mq = MagicMock()
        mq.get.side_effect = [
            queue.Empty,
            {"event": "download.completed", "data": {"task_id": "1"}},
            queue.Empty,
        ]

        gen = _event_stream_generator(mq)
        assert next(gen) == ": keepalive\n\n"
        line = next(gen)
        assert "event: download.completed" in line
        assert "1" in line
        assert next(gen) == ": keepalive\n\n"


class TestDownloadEventsSSE:
    def test_auth_required(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(download_router.router, prefix="/api/download")
        app.state.context = MagicMock()
        with TestClient(app) as c:
            resp = c.get("/api/download/events")
        assert resp.status_code == 401

    def test_permission_required(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(download_router.router, prefix="/api/download")
        user_ctx = UserContext(
            user_id=2,
            username="user",
            level=0,
            permissions=[],
        )
        app.dependency_overrides[get_current_user] = lambda: user_ctx
        with TestClient(app) as c:
            resp = c.get("/api/download/events")
        assert resp.status_code == 403

    def test_returns_200_and_event_stream_type(self, client):
        with patch("api.routers.download._event_stream_generator", return_value=iter([b"data: ok\n\n"])):
            resp = client.get("/api/download/events")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert b"data: ok" in resp.content


class TestBrowseDownloaderDirs:
    @pytest.fixture
    def mock_downloader_service(self):
        svc = MagicMock()
        svc.get_remote_dirs.return_value = ["/downloads", "/downloads/movies"]
        return svc

    @pytest.fixture
    def dir_client(self, mock_downloader_service):
        app = FastAPI()
        app.include_router(download_router.router, prefix="/api/download")
        user_ctx = UserContext(
            user_id=1,
            username="admin",
            level=0,
            permissions=["download:view", "download:manage"],
        )
        app.dependency_overrides[get_current_user] = lambda: user_ctx
        app.dependency_overrides[get_downloader_service] = lambda: mock_downloader_service
        with TestClient(app) as c:
            yield c

    def test_returns_dirs_with_dict_config(self, dir_client, mock_downloader_service):
        resp = dir_client.post(
            "/api/download/downloaders/browse_dirs",
            json={"type": "qbittorrent", "config": {"host": "127.0.0.1"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"count": 2, "items": ["/downloads", "/downloads/movies"]}
        mock_downloader_service.get_remote_dirs.assert_called_once_with(
            dtype="qbittorrent", config={"host": "127.0.0.1"}
        )

    def test_accepts_json_string_config(self, dir_client, mock_downloader_service):
        resp = dir_client.post(
            "/api/download/downloaders/browse_dirs",
            json={"type": "qbittorrent", "config": '{"host": "127.0.0.1"}'},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_downloader_service.get_remote_dirs.assert_called_once_with(
            dtype="qbittorrent", config={"host": "127.0.0.1"}
        )

    def test_missing_type_fails(self, dir_client, mock_downloader_service):
        resp = dir_client.post("/api/download/downloaders/browse_dirs", json={"config": {}})
        assert resp.status_code == 200
        assert resp.json()["code"] != 0
        mock_downloader_service.get_remote_dirs.assert_not_called()

    def test_invalid_config_json_fails(self, dir_client, mock_downloader_service):
        resp = dir_client.post(
            "/api/download/downloaders/browse_dirs",
            json={"type": "qbittorrent", "config": "{invalid"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] != 0
        mock_downloader_service.get_remote_dirs.assert_not_called()

    def test_service_error_returns_fail(self, dir_client, mock_downloader_service):
        mock_downloader_service.get_remote_dirs.side_effect = RuntimeError("连接失败")
        resp = dir_client.post(
            "/api/download/downloaders/browse_dirs",
            json={"type": "qbittorrent", "config": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] != 0
        assert "连接失败" in resp.json()["message"]
