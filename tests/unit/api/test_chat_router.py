"""Agent 对话 Router 单元测试"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_app_context, get_current_user
from api.routers import chat as chat_router
from app.schemas.auth import UserContext


def _make_client(agent_ready=True, conversation_store=None, answer="这是回答"):
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/agent")
    admin = UserContext(user_id=1, username="admin", level=0, permissions=["agent:view"])
    app.dependency_overrides[get_current_user] = lambda: admin

    agent_service = MagicMock()
    agent_service.ready = agent_ready
    agent_service.chat_agent.chat_with_tools.return_value = answer
    ctx = SimpleNamespace(agent_service=agent_service, conversation_store=conversation_store)
    app.dependency_overrides[get_app_context] = lambda: ctx
    return TestClient(app), agent_service


class TestChatRouter:
    def test_chat_sse_stream(self):
        client, agent_service = _make_client()
        with client.stream("POST", "/api/agent/chat", json={"question": "系统状态如何"}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
        assert '"type": "answer"' in body
        assert "这是回答" in body

    def test_chat_empty_question(self):
        client, _ = _make_client()
        resp = client.post("/api/agent/chat", json={"question": "  "})
        assert resp.json()["code"] != 0

    def test_chat_agent_not_ready(self):
        client, _ = _make_client(agent_ready=False)
        resp = client.post("/api/agent/chat", json={"question": "你好"})
        assert resp.json()["code"] != 0

    def test_chat_clear(self):
        store = MagicMock()
        client, _ = _make_client(conversation_store=store)
        resp = client.post("/api/agent/chat/clear", json={"session_id": "s1"})
        assert resp.json()["code"] == 0
        store.clear_session.assert_called_once_with(session_id="s1", user_id="1", channel="web")

    def test_chat_clear_disabled(self):
        client, _ = _make_client(conversation_store=None)
        resp = client.post("/api/agent/chat/clear", json={"session_id": "s1"})
        assert resp.json()["code"] != 0

    def test_permission_denied(self):
        app = FastAPI()
        app.include_router(chat_router.router, prefix="/api/agent")
        guest = UserContext(user_id=2, username="guest", level=99, permissions=[])
        app.dependency_overrides[get_current_user] = lambda: guest
        with TestClient(app) as c:
            resp = c.post("/api/agent/chat", json={"question": "hi"})
        assert resp.status_code == 403
