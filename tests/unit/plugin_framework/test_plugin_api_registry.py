"""插件自定义 API 注册表与调度路由单元测试."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user
from api.routers import plugin_framework as plugin_router
from app.plugin_framework import api_registry
from app.schemas.auth import UserContext


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    api_registry.unregister_plugin_apis("testplugin")
    api_registry.unregister_plugin_apis("other")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(plugin_router.router, prefix="/api/plugin-framework")
    user_ctx = UserContext(
        user_id=1,
        username="admin",
        level=0,
        permissions=["plugin:view", "plugin:manage"],
    )
    app.dependency_overrides[get_current_user] = lambda: user_ctx
    with TestClient(app) as c:
        yield c


class TestApiRegistry:
    def test_register_and_get(self):
        handler = lambda params: {"ok": True}  # noqa: E731
        api_registry.register_api("testplugin", "status", handler)
        assert api_registry.get_api_handler("testplugin", "status") is handler
        assert api_registry.get_api_handler("testplugin", "/status/") is handler

    def test_unregister_plugin_apis(self):
        api_registry.register_api("testplugin", "a", lambda p: None)
        api_registry.register_api("testplugin", "b", lambda p: None)
        api_registry.register_api("other", "a", lambda p: None)
        api_registry.unregister_plugin_apis("testplugin")
        assert api_registry.get_api_handler("testplugin", "a") is None
        assert api_registry.get_api_handler("testplugin", "b") is None
        assert api_registry.get_api_handler("other", "a") is not None


class TestPluginApiDispatch:
    def test_get_with_query_params(self, client):
        seen = {}

        def handler(params):
            seen.update(params)
            return {"success": True, "data": {"echo": params.get("x")}}

        api_registry.register_api("testplugin", "echo", handler)
        resp = client.get("/api/plugin-framework/plugins/testplugin/api/echo?x=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"echo": "1"}
        assert seen == {"x": "1"}

    def test_post_merges_json_body(self, client):
        def handler(params):
            return {"success": True, "data": params}

        api_registry.register_api("testplugin", "bind", handler)
        resp = client.post(
            "/api/plugin-framework/plugins/testplugin/api/bind?from=query",
            json={"site": "hdhome", "uid": "1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"from": "query", "site": "hdhome", "uid": "1"}

    def test_success_false_maps_to_fail(self, client):
        api_registry.register_api("testplugin", "bad", lambda p: {"success": False, "message": "绑定失败"})
        resp = client.post("/api/plugin-framework/plugins/testplugin/api/bad", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] != 0
        assert body["message"] == "绑定失败"

    def test_plain_result_wrapped(self, client):
        api_registry.register_api("testplugin", "list", lambda p: [1, 2, 3])
        resp = client.get("/api/plugin-framework/plugins/testplugin/api/list")
        assert resp.json()["data"] == [1, 2, 3]

    def test_unknown_path_fails(self, client):
        resp = client.get("/api/plugin-framework/plugins/testplugin/api/not-exist")
        assert resp.status_code == 200
        assert resp.json()["code"] != 0

    def test_handler_exception_fails(self, client):
        def boom(params):
            raise RuntimeError("炸了")

        api_registry.register_api("testplugin", "boom", boom)
        resp = client.get("/api/plugin-framework/plugins/testplugin/api/boom")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] != 0
        assert "炸了" in body["message"]
