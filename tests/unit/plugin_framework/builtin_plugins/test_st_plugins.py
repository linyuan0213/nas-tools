"""存储后端插件化框架能力测试."""

from unittest.mock import MagicMock, patch

from app.plugin_framework.builtin_plugins._st_common.storage_lifecycle import (
    disable_storage_records,
)
from app.storage.backends.local import LocalStorageBackend
from app.storage.config_models import LocalStorageConfig
from app.storage.factory import StorageBackendFactory


class TestStorageRegistry:
    def test_unregister(self):
        from app.storage.backends.base import StorageType

        stype = StorageType.WEBDAV
        StorageBackendFactory.register(stype, LocalStorageBackend, config_cls=None)
        assert stype in StorageBackendFactory.list_supported_types()
        StorageBackendFactory.unregister(stype)
        assert stype not in StorageBackendFactory.list_supported_types()

    def test_register_string_type_key(self):
        """插件可用字符串标识注册新后端（无需扩展枚举）"""
        StorageBackendFactory.register(
            "plugin_backend",
            LocalStorageBackend,
            config_cls=LocalStorageConfig,
            type_key="plugin_backend",
        )
        assert "plugin_backend" in StorageBackendFactory.list_registered_type_keys()
        assert "plugin_backend" in StorageBackendFactory.list_supported_types()
        schema = StorageBackendFactory.get_type_schema()
        assert any(item["key"] == "plugin_backend" for item in schema)
        StorageBackendFactory.unregister("plugin_backend", type_key="plugin_backend")
        assert "plugin_backend" not in StorageBackendFactory.list_registered_type_keys()
        assert "plugin_backend" not in StorageBackendFactory.list_supported_types()


class TestStorageLifecycle:
    def test_disable_storage_records(self):
        record = MagicMock()
        record.TYPE = "rclone"
        record.ENABLED = 1
        record.ID = 5
        repo_mock = MagicMock()
        repo_mock.get_all.return_value = [record]
        with patch(
            "app.plugin_framework.builtin_plugins._st_common.storage_lifecycle.StorageBackendRepository",
            return_value=repo_mock,
        ):
            disable_storage_records("rclone")
        repo_mock.update.assert_called_once_with(5, ENABLED=0)

    def test_disable_skips_disabled_or_other_type(self):
        disabled = MagicMock(TYPE="rclone", ENABLED=0)
        other = MagicMock(TYPE="smb", ENABLED=1)
        repo_mock = MagicMock()
        repo_mock.get_all.return_value = [disabled, other]
        with patch(
            "app.plugin_framework.builtin_plugins._st_common.storage_lifecycle.StorageBackendRepository",
            return_value=repo_mock,
        ):
            disable_storage_records("rclone")
        repo_mock.update.assert_not_called()
