"""错误码与统一响应测试"""

import pytest

from app.core.error_codes import ErrorCode, default_http_status, default_message
from app.core.exceptions import (
    AuthError,
    NexusError,
    PermissionDenied,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.response import fail, success


class TestErrorCode:
    def test_success_is_zero(self):
        assert ErrorCode.SUCCESS == 0

    def test_every_code_has_meta(self):
        for code in ErrorCode:
            assert default_message(code)
            assert 200 <= default_http_status(code) < 600

    def test_code_segments(self):
        assert 10_000 <= ErrorCode.PARAM_VALIDATION_FAILED < 20_000
        assert 20_000 <= ErrorCode.UNAUTHORIZED < 30_000
        assert 30_000 <= ErrorCode.MEDIA_NOT_FOUND < 40_000
        assert 40_000 <= ErrorCode.TORRENT_ADD_FAILED < 50_000
        assert 50_000 <= ErrorCode.SITE_NOT_FOUND < 60_000
        assert 60_000 <= ErrorCode.SUBSCRIPTION_NOT_FOUND < 70_000
        assert 70_000 <= ErrorCode.PLUGIN_NOT_FOUND < 80_000
        assert 80_000 <= ErrorCode.SYNC_FAILED < 90_000
        assert 90_000 <= ErrorCode.DATABASE_ERROR < 100_000


class TestNexusError:
    def test_default_errcode_from_subclass(self):
        exc = ResourceNotFoundError("站点不存在")
        assert exc.errcode == ErrorCode.RESOURCE_NOT_FOUND
        assert exc.http_status == 404
        assert exc.message == "站点不存在"

    def test_default_message_fallback(self):
        exc = PermissionDenied()
        assert exc.errcode == ErrorCode.PERMISSION_DENIED
        assert exc.message == default_message(ErrorCode.PERMISSION_DENIED)

    def test_explicit_errcode_override(self):
        exc = NexusError("自定义", errcode=ErrorCode.DOWNLOADER_CONNECT_FAILED, http_status=502)
        assert exc.errcode == ErrorCode.DOWNLOADER_CONNECT_FAILED
        assert exc.http_status == 502

    def test_auth_error(self):
        exc = AuthError("token 过期")
        assert exc.errcode == ErrorCode.UNAUTHORIZED
        assert exc.http_status == 401

    def test_to_dict(self):
        exc = ValidationError("参数错误", details={"field": "name"})
        d = exc.to_dict()
        assert d["errcode"] == int(ErrorCode.PARAM_VALIDATION_FAILED)
        assert d["message"] == "参数错误"
        assert d["details"] == {"field": "name"}


class TestResponse:
    def test_success_structure(self):
        r = success(data={"a": 1})
        assert r["code"] == 0
        assert r["data"] == {"a": 1}
        assert "message" in r

    def test_fail_with_errcode(self):
        r = fail(code=ErrorCode.SITE_NOT_FOUND)
        assert r["code"] == ErrorCode.SITE_NOT_FOUND
        assert r["message"] == "站点不存在"

    def test_fail_custom_msg(self):
        r = fail(code=ErrorCode.TORRENT_ADD_FAILED, msg="磁力链接无效")
        assert r["message"] == "磁力链接无效"

    def test_fail_legacy_int_code(self):
        r = fail(code=1, msg="旧格式")
        assert r["code"] == 1
        assert r["message"] == "旧格式"


class TestNewCodes:
    def test_new_errcode_meta(self):
        assert default_message(ErrorCode.FILE_OPERATION_FAILED)
        assert default_message(ErrorCode.APIKEY_INVALID)
        assert default_message(ErrorCode.IMAGE_FETCH_FAILED)
        assert default_message(ErrorCode.PLUGIN_INSTALLING)
        assert default_message(ErrorCode.PLUGIN_HOT_RELOAD_FAILED)

    def test_plugin_subclasses(self):
        from app.core.exceptions import (
            PluginHotReloadError,
            PluginInstallingError,
            PluginManifestInvalidError,
            PluginNotInstalledError,
        )

        assert PluginNotInstalledError().http_status == 404
        assert PluginInstallingError().errcode == ErrorCode.PLUGIN_INSTALLING
        assert PluginInstallingError().http_status == 409
        assert PluginManifestInvalidError().errcode == ErrorCode.PLUGIN_MANIFEST_INVALID
        assert PluginHotReloadError().errcode == ErrorCode.PLUGIN_HOT_RELOAD_FAILED

    def test_registry_drives_http_status(self):
        from app.core.exceptions import NexusError

        # http_status 未显式传入时，由错误码注册表决定（单一事实来源）
        assert NexusError(errcode=ErrorCode.PASSWORD_INCORRECT).http_status == 401
        assert NexusError(errcode=ErrorCode.APIKEY_INVALID).http_status == 401
        assert NexusError(errcode=ErrorCode.PLUGIN_INSTALLING).http_status == 409
        assert NexusError(errcode=ErrorCode.PLUGIN_MANIFEST_INVALID).http_status == 400

    def test_headers_passed_through(self):
        from app.core.exceptions import NexusError

        exc = NexusError("认证失败", headers={"WWW-Authenticate": "Bearer"})
        assert exc.headers == {"WWW-Authenticate": "Bearer"}


class TestExceptionHandlers:
    async def _req(self):
        from starlette.requests import Request

        scope = {"type": "http", "method": "GET", "path": "/api/x", "headers": []}
        return Request(scope)

    @pytest.mark.asyncio
    async def test_nexus_handler_payload(self):
        import json

        from api.exception_handlers import nexus_error_handler
        from app.core.exceptions import PermissionDenied

        resp = await nexus_error_handler(await self._req(), PermissionDenied("无权限"))
        assert resp.status_code == 403
        body = json.loads(bytes(resp.body))
        assert body["code"] == int(ErrorCode.PERMISSION_DENIED)
        assert body["message"] == "无权限"

    @pytest.mark.asyncio
    async def test_http_handler_maps_status(self):
        import json

        from starlette.exceptions import HTTPException

        from api.exception_handlers import http_exception_handler

        resp = await http_exception_handler(await self._req(), HTTPException(status_code=404, detail="不存在"))
        assert resp.status_code == 404
        body = json.loads(bytes(resp.body))
        assert body["code"] == int(ErrorCode.RESOURCE_NOT_FOUND)
