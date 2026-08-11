"""Agent 知识库 Router 单元测试"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user, get_knowledge_ingestor, get_retriever
from api.exception_handlers import register_exception_handlers
from api.routers import kb as kb_router
from app.agent.rag.retriever import RetrievalResult
from app.schemas.auth import UserContext


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(kb_router.router, prefix="/api/agent")
    admin = UserContext(user_id=1, username="admin", level=0, permissions=["agent:view", "agent:manage"])
    app.dependency_overrides[get_current_user] = lambda: admin

    ingestor = MagicMock()
    ingestor.status.return_value = {"faq": 10}
    ingestor.reindex.return_value = {"faq": 10}
    retriever = MagicMock()
    retriever.search.return_value = RetrievalResult(
        chunks=[MagicMock()],
        citations=[{"source": "docs/a.md", "heading": "安装", "snippet": "内容"}],
    )

    app.dependency_overrides[get_knowledge_ingestor] = lambda: ingestor
    app.dependency_overrides[get_retriever] = lambda: retriever
    with TestClient(app) as c:
        yield SimpleNamespace(client=c, ingestor=ingestor, retriever=retriever)


@pytest.fixture
def client_no_rag():
    app = FastAPI()
    app.include_router(kb_router.router, prefix="/api/agent")
    admin = UserContext(user_id=1, username="admin", level=0, permissions=["agent:view", "agent:manage"])
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_knowledge_ingestor] = lambda: None
    app.dependency_overrides[get_retriever] = lambda: None
    with TestClient(app) as c:
        yield c


class TestKbRouter:
    def test_status(self, client):
        resp = client.client.post("/api/agent/kb/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["namespaces"] == {"faq": 10}

    def test_reindex(self, client):
        resp = client.client.post("/api/agent/kb/reindex", json={"namespace": "faq"})
        assert resp.status_code == 200
        client.ingestor.reindex.assert_called_once_with("faq")

    def test_reindex_invalid_namespace(self, client):
        resp = client.client.post("/api/agent/kb/reindex", json={"namespace": "bad"})
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_search(self, client):
        resp = client.client.post("/api/agent/kb/search", json={"query": "下载器"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["citations"][0]["source"] == "docs/a.md"

    def test_permission_denied(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(kb_router.router, prefix="/api/agent")
        guest = UserContext(user_id=2, username="guest", level=99, permissions=[])
        app.dependency_overrides[get_current_user] = lambda: guest
        with TestClient(app) as c:
            resp = c.post("/api/agent/kb/status")
        assert resp.status_code == 403

    def test_rag_disabled(self, client_no_rag):
        resp = client_no_rag.post("/api/agent/kb/status")
        assert resp.status_code == 200
        assert resp.json()["code"] != 0
