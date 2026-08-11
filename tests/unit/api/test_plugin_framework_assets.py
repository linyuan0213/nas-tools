"""Plugin framework asset router 单元测试."""

from unittest.mock import MagicMock, patch

from fastapi import Response
from fastapi.responses import FileResponse

from api.routers import plugin_framework as plugin_router


class TestPluginAsset:
    def test_get_plugin_asset_missing_frontend_returns_empty_esm(self):
        svc = MagicMock()
        svc.get_plugin_path.return_value = "/tmp/plugins/doubansync"
        with patch("api.routers.plugin_framework.os.path.exists", return_value=False):
            resp = plugin_router.get_plugin_asset(
                plugin_id="doubansync", file_path="assets/frontend/index.mjs", svc=svc
            )
        assert isinstance(resp, Response)
        assert resp.status_code == 200
        assert resp.media_type == "application/javascript"
        assert b"export default {}" in resp.body

    def test_get_plugin_asset_missing_other_returns_fail(self):
        svc = MagicMock()
        svc.get_plugin_path.return_value = "/tmp/plugins/doubansync"
        with patch("api.routers.plugin_framework.os.path.exists", return_value=False):
            resp = plugin_router.get_plugin_asset(plugin_id="doubansync", file_path="assets/other.js", svc=svc)
        assert resp.get("code") != 0  # type: ignore[attr-defined]

    def test_get_plugin_asset_strips_assets_prefix(self):
        svc = MagicMock()
        svc.get_plugin_path.return_value = "/tmp/plugins/autosignin"
        with patch(
            "api.routers.plugin_framework.os.path.exists",
            side_effect=lambda path: path.endswith("frontend/index.mjs"),
        ):
            with patch(
                "api.routers.plugin_framework.os.path.isfile",
                side_effect=lambda path: path.endswith("frontend/index.mjs"),
            ):
                resp = plugin_router.get_plugin_asset(
                    plugin_id="autosignin", file_path="assets/frontend/index.mjs", svc=svc
                )
        assert isinstance(resp, FileResponse)
