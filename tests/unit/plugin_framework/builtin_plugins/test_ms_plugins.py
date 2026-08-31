"""媒体服务器插件化框架能力测试."""

from unittest.mock import MagicMock, patch

from app.mediaserver import registry as ms_registry
from app.plugin_framework.builtin_plugins._ms_common.mediaserver_lifecycle import (
    disable_mediaserver_record,
)


class TestMediaServerRegistry:
    def test_unregister(self):
        class _FakeMS:
            client_id = "__fake_ms__"

        ms_registry.register(_FakeMS)
        assert ms_registry.get_client_class("__fake_ms__") is _FakeMS
        ms_registry.unregister("__fake_ms__")
        assert ms_registry.get_client_class("__fake_ms__") is None

    def test_unregister_missing_is_noop(self):
        ms_registry.unregister("__nonexistent__")


class TestMediaServerLifecycle:
    def test_disable_mediaserver_record(self):
        record = MagicMock()
        record.NAME = "emby"
        record.ENABLED = 1
        record.ID = 5
        record.CONFIG = "{}"
        record.IS_DEFAULT = 0
        repo_mock = MagicMock()
        repo_mock.get_media_servers.return_value = [record]
        with patch(
            "app.plugin_framework.builtin_plugins._ms_common.mediaserver_lifecycle.MediaServerRepositoryAdapter",
            return_value=repo_mock,
        ):
            disable_mediaserver_record("emby")
        repo_mock.update_media_server.assert_called_once_with(
            sid=5, name="emby", enabled=0, config="{}", is_default=0
        )

    def test_disable_skips_disabled_or_other_type(self):
        disabled = MagicMock(NAME="emby", ENABLED=0)
        other = MagicMock(NAME="jellyfin", ENABLED=1)
        repo_mock = MagicMock()
        repo_mock.get_media_servers.return_value = [disabled, other]
        with patch(
            "app.plugin_framework.builtin_plugins._ms_common.mediaserver_lifecycle.MediaServerRepositoryAdapter",
            return_value=repo_mock,
        ):
            disable_mediaserver_record("emby")
        repo_mock.update_media_server.assert_not_called()
