"""PluginRegistry 单元测试."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.plugin_framework.registry import PluginRegistry
from app.schemas.plugin import PluginManifest


def _build_registry(tmp_path, builtin_dir=None):
    """构建测试用 PluginRegistry，隔离内置插件目录."""
    with (
        patch("app.plugin_framework.registry.settings") as mock_settings,
        patch.object(PluginRegistry, "_load_all"),
        patch.object(PluginRegistry, "_scan_builtin_plugins"),
    ):
        mock_settings.data_path = str(tmp_path)
        repo = MagicMock()
        repo.get_all_manifests.return_value = []
        reg = PluginRegistry(repo=repo)
        if builtin_dir:
            reg._builtin_dir = str(builtin_dir)
        return reg


@pytest.fixture
def registry(tmp_path):
    return _build_registry(tmp_path, builtin_dir=tmp_path / "builtin_plugins")


class TestPluginRegistryScan:
    """测试插件扫描性能优化."""

    def test_scan_does_not_rescan_within_throttle(self, registry):
        """60 秒内重复 scan 不应重新扫描内置插件."""
        with patch.object(registry, "_scan_builtin_plugins") as mock_scan:
            registry.scan()
            registry.scan()
            registry.scan()
        assert mock_scan.call_count == 1

    def test_scan_allows_rescan_after_throttle(self, registry):
        """超过 60 秒后再次 scan 才允许重新扫描."""
        with (
            patch("app.plugin_framework.registry.time.time", side_effect=[100, 130, 200]),
            patch.object(registry, "_scan_builtin_plugins") as mock_scan,
        ):
            registry.scan()
            registry.scan()
            registry.scan()
        assert mock_scan.call_count == 2

    def _write_manifest(self, plugin_dir, manifest_data):
        import json

        with open(plugin_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

    def _minimal_manifest(self, manifest_id, version):
        return {
            "manifest_version": "1.0",
            "id": manifest_id,
            "name": "Test Plugin",
            "version": version,
            "author": "",
            "author_url": "",
            "description": "",
            "category": "tool",
            "tags": [],
            "icon": "",
            "color": "",
            "min_app_version": "",
            "backend": {
                "entry": "backend.plugin",
                "api_prefix": "/api/test-plugin",
                "permissions": [],
                "hooks": {},
                "supports_run": False,
                "dependencies": [],
            },
            "frontend": {"routes": [], "slots": []},
        }

    def test_scan_skips_db_update_if_manifest_unchanged(self, registry, tmp_path):
        """内置插件 manifest 未变化时不应写入数据库."""
        builtin_dir = tmp_path / "builtin_plugins"
        builtin_dir.mkdir()
        plugin_dir = builtin_dir / "test_plugin"
        plugin_dir.mkdir()
        manifest_data = self._minimal_manifest("test_plugin", "1.0.0")
        self._write_manifest(plugin_dir, manifest_data)

        registry._builtin_dir = str(builtin_dir)
        existing_orm = MagicMock()
        existing_orm.ENABLED = True
        existing_orm.INSTALLED = True
        # 库中存量行 JSON 为规范化后的 to_dict 产物（含可选字段默认值），与扫描对比基准一致
        existing_orm.MANIFEST_JSON = json.dumps(PluginManifest.from_dict(manifest_data).to_dict(), ensure_ascii=False)
        registry._repo.get_manifest_by_id.return_value = existing_orm

        registry._scan_builtin_plugins()

        registry._repo.update_manifest.assert_not_called()
        registry._repo.insert_manifest.assert_not_called()

    def test_scan_updates_db_if_manifest_changed(self, registry, tmp_path):
        """内置插件 manifest 变化时应写入数据库."""
        builtin_dir = tmp_path / "builtin_plugins"
        builtin_dir.mkdir()
        plugin_dir = builtin_dir / "test_plugin"
        plugin_dir.mkdir()
        manifest_data = self._minimal_manifest("test_plugin", "2.0.0")
        self._write_manifest(plugin_dir, manifest_data)

        registry._builtin_dir = str(builtin_dir)
        existing_orm = MagicMock()
        existing_orm.ENABLED = True
        existing_orm.INSTALLED = True
        existing_orm.MANIFEST_JSON = json.dumps({"old": "data"}, ensure_ascii=False)
        registry._repo.get_manifest_by_id.return_value = existing_orm

        registry._scan_builtin_plugins()

        registry._repo.update_manifest.assert_called_once()


def _minimal_manifest_dict(manifest_id="test_plugin", version="1.0.0"):
    return {
        "manifest_version": "1.0",
        "id": manifest_id,
        "name": "Test Plugin",
        "version": version,
        "author": "",
        "author_url": "",
        "description": "",
        "category": "tool",
        "tags": [],
        "icon": "",
        "color": "",
        "min_app_version": "",
        "backend": {
            "entry": "backend.plugin",
            "api_prefix": "/api/test-plugin",
            "permissions": [],
            "hooks": {},
            "supports_run": False,
            "dependencies": [],
        },
        "frontend": {"routes": [], "slots": []},
    }


class TestRegistrySaveManifestUpsert:
    """同 id 清单已存在时安装应更新而非插入（修复 Duplicate PRIMARY）."""

    def test_save_updates_when_row_exists(self, registry):
        manifest = PluginManifest.from_dict(_minimal_manifest_dict())
        registry._repo.get_manifest_by_id.return_value = MagicMock()
        registry._save_manifest(manifest, "/data/plugins/test_plugin-1.0.0")
        registry._repo.update_manifest.assert_called_once()
        registry._repo.insert_manifest.assert_not_called()

    def test_save_inserts_when_no_row(self, registry):
        manifest = PluginManifest.from_dict(_minimal_manifest_dict())
        registry._repo.get_manifest_by_id.return_value = None
        registry._save_manifest(manifest, "/data/plugins/test_plugin-1.0.0")
        registry._repo.insert_manifest.assert_called_once()
        registry._repo.update_manifest.assert_not_called()
