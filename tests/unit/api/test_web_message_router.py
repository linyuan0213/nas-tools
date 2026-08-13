"""WebMessageStore 与内置消息 Router 单元测试"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_app_context, get_current_user
from api.routers import web_message as web_message_router
from app.message.web_store import WebMessageStore
from app.schemas.auth import UserContext


@pytest.fixture
def store():
    s = WebMessageStore(maxlen=10, enable_db=False)
    yield s


class TestWebMessageStoreMultiUser:
    def test_user_isolation(self):
        s = WebMessageStore(enable_db=False)
        s.add(title="全局通知", kind="notify")
        s.add(title="用户A回复", kind="reply", user_id="1")
        s.add(title="用户B回复", kind="reply", user_id="2")
        a = s.after(0, user_id="1")
        assert [i["title"] for i in a] == ["全局通知", "用户A回复"]
        b = s.after(0, user_id="2")
        assert [i["title"] for i in b] == ["全局通知", "用户B回复"]

    def test_guest_sees_global_only(self):
        s = WebMessageStore(enable_db=False)
        s.add(title="全局", kind="notify")
        s.add(title="A的", kind="reply", user_id="1")
        guest = s.after(0, user_id="99")
        assert [i["title"] for i in guest] == ["全局"]

    def test_default_user_id_global(self):
        s = WebMessageStore(enable_db=False)
        s.add(title="无user_id", kind="notify")
        assert s.after(0, user_id="x")[0]["title"] == "无user_id"


class TestWebMessageStore:
    def test_add_and_after(self, store):
        store.add(title="t1", content="c1")
        store.add(title="t2", content="c2", kind="reply")
        items = store.after(0)
        assert len(items) == 2
        assert items[0]["cursor"] == 1
        assert items[1]["kind"] == "reply"

    def test_cursor_incremental(self, store):
        first = store.add(title="t1")
        store.add(title="t2")
        items = store.after(first["cursor"])
        assert [i["title"] for i in items] == ["t2"]

    def test_maxlen_eviction(self, store):
        for i in range(15):
            store.add(title=f"t{i}")
        assert len(store.after(0)) == 10

    def test_singleton(self):
        assert WebMessageStore.instance() is WebMessageStore.instance()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(web_message_router.router, prefix="/api/agent")
    admin = UserContext(user_id=1, username="admin", level=0, permissions=["agent:view"])
    app.dependency_overrides[get_current_user] = lambda: admin
    handler = MagicMock()
    ctx = SimpleNamespace(message=MagicMock())
    app.dependency_overrides[get_app_context] = lambda: ctx
    with (
        patch(
            "api.routers.web_message.get_message_command_handler", return_value=handler
        ) as _,
        TestClient(app) as c,
    ):
        yield SimpleNamespace(client=c, handler=handler)


class TestWebMessageRouter:
    def test_interact_dispatches_command(self, client):
        resp = client.client.post("/api/agent/message/interact", json={"text": "订阅 流浪地球"})
        assert resp.json()["code"] == 0
        client.handler.handle_message_job.assert_called_once()
        kwargs = client.handler.handle_message_job.call_args.kwargs
        assert kwargs["msg"] == "订阅 流浪地球"
        assert kwargs["user_id"] == "1"

    def test_interact_empty_rejected(self, client):
        resp = client.client.post("/api/agent/message/interact", json={"text": "  "})
        assert resp.json()["code"] != 0

    def test_interact_permission_denied(self):
        app = FastAPI()
        app.include_router(web_message_router.router, prefix="/api/agent")
        guest = UserContext(user_id=2, username="g", level=99, permissions=[])
        app.dependency_overrides[get_current_user] = lambda: guest
        from api.exception_handlers import register_exception_handlers

        register_exception_handlers(app)
        with TestClient(app) as c:
            resp = c.post("/api/agent/message/interact", json={"text": "x"})
        assert resp.status_code == 403

    def test_stream_endpoint_exists(self, client):
        # 仅验证路由注册（FastAPI 0.139 惰性路由：检查 _IncludedRouter 原始路由）
        inc = [r for r in client.client.app.router.routes if type(r).__name__ == "_IncludedRouter"]
        paths = [getattr(x, "path", "") for r in inc for x in getattr(r, "original_router", r).routes]
        assert "/message/stream" in paths
