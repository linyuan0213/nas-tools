"""System API Router 单元测试."""

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user
from api.exception_handlers import register_exception_handlers
from api.routers import system as system_router
from app.infrastructure.progress import ProgressTracker
from app.schemas.auth import UserContext


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(system_router.router, prefix="/api/v1/system")
    admin_ctx = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["log:view"],
    )
    app.dependency_overrides[get_current_user] = lambda: admin_ctx
    with TestClient(app) as c:
        yield c


class TestSystemRouter:
    def test_stream_logging_missing_token(self, client):
        """缺少 token 时返回 401."""
        resp = client.get("/api/v1/system/stream-logging")
        assert resp.status_code == 401

    def test_stream_logging_invalid_token(self, client):
        """无效 token 时返回 401."""
        with patch("app.services.auth_service.AuthService.verify_token", return_value=None):
            resp = client.get("/api/v1/system/stream-logging?token=invalid")
        assert resp.status_code == 401

    def test_stream_logging_forbidden(self, client):
        """非超管且无 log:view 权限时返回 403."""
        user_ctx = UserContext(
            user_id=2,
            username="user",
            level=0,
            permissions=[],
        )
        with patch("app.services.auth_service.AuthService.verify_token", return_value=user_ctx):
            resp = client.get("/api/v1/system/stream-logging?token=valid")
        assert resp.status_code == 403

    def test_stream_logging_success(self, client):
        """有效超管 token 可建立日志流."""
        admin_ctx = UserContext(
            user_id=1,
            username="admin",
            level=0,
            permissions=["log:view"],
        )
        stream_mock = MagicMock()
        stream_mock.__iter__ = MagicMock(return_value=iter([b"data: log\n\n"]))

        with patch("app.services.auth_service.AuthService.verify_token", return_value=admin_ctx):
            with patch("api.routers.system.LogStreamingService") as mock_service_cls:
                mock_service = MagicMock()
                mock_service.stream.return_value = stream_mock
                mock_service_cls.return_value = mock_service
                resp = client.get("/api/v1/system/stream-logging?token=valid")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

    def test_search_progress_unknown_session_ends_quickly(self, client):
        """无进度记录的会话（后端重启后刷新页面）应快速关闭 SSE，而不是挂到 600s 上限."""
        start = time.monotonic()
        with client.stream("GET", f"/api/v1/system/search/progress/{uuid.uuid4()}") as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes())
        elapsed = time.monotonic() - start
        assert elapsed < 15
        assert body == b""

    def test_search_progress_completed_session_yields_and_closes(self, client):
        """已完成的会话（enable=False 且 value=100）推送一次后立即关闭."""
        key = f"search:{uuid.uuid4()}"
        tracker = ProgressTracker()
        tracker.start(key)
        tracker.end(key)
        try:
            with client.stream("GET", f"/api/v1/system/search/progress/{key.removeprefix('search:')}") as resp:
                assert resp.status_code == 200
                body = b"".join(resp.iter_bytes())
            assert b"100" in body
        finally:
            ProgressTracker._process_detail.pop(key, None)
