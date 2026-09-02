"""下载历史 / 插件 agent 工具测试"""

from typing import cast

from app.agent.tools.context import ToolContext
from app.agent.tools.handlers.download import download_history_list
from app.agent.tools.handlers.plugins import (
    plugin_config_save,
    plugin_disable,
    plugin_enable,
    plugin_info,
    plugin_list,
    plugin_run,
)


class _Row:
    def __init__(self, title, se="", state="", date="", year="2026", tmdb="1"):
        self.TITLE = title
        self.SE = se
        self.STATE = state
        self.DATE = date
        self.YEAR = year
        self.TMDBID = tmdb
        self.TYPE = "tv"


class _DownloaderCore:
    def __init__(self, rows):
        self.rows = rows
        self.fail = False
        self.calls = []

    def get_download_history(self, date=None, hid=None, num=30, page=1):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((page, num))
        return self.rows


class _PluginService:
    def __init__(self, plugins, configs=None):
        self.plugins = plugins
        self.configs = configs or {}
        self.ran = []
        self.enabled: list[str] = []
        self.disabled: list[str] = []
        self.saved: list[tuple] = []

    def list_plugins(self):
        return self.plugins

    def get_config(self, plugin_id):
        return self.configs.get(plugin_id, {})

    def get_manifest(self, plugin_id):
        for p in self.plugins:
            if p.get("id") == plugin_id:
                backend = type("B", (), {"supports_run": p.get("supports_run")})
                return type("M", (), {"name": p.get("name"), "backend": backend()})()
        return None

    def run_plugin(self, plugin_id):
        self.ran.append(plugin_id)

    def enable(self, plugin_id):
        self.enabled.append(plugin_id)

    def disable(self, plugin_id):
        self.disabled.append(plugin_id)

    def save_config(self, plugin_id, config):
        self.saved.append((plugin_id, config))


def _ctx(downloader=None, plugins=None):
    return cast(
        ToolContext,
        ToolContext(
            search_orchestrator=None,
            searcher=None,
            download_service=None,
            downloader_core=downloader,
            subscribe_service=None,
            media_service=None,
            media_info_service=None,
            filetransfer_service=None,
            scheduler_service=None,
            system_info_service=None,
            event_bus=None,
            plugin_framework_service=plugins,
        ),
    )


def _data(result) -> dict:
    assert isinstance(result.data, dict)
    return result.data


class TestDownloadHistoryList:
    def test_returns_history(self):
        core = _DownloaderCore(
            [
                _Row("流浪地球", "S01 E01", "completed", "2026-08-01"),
                _Row("电锯人", "S01 E07", "downloading", "2026-08-02"),
            ]
        )
        result = download_history_list(_ctx(downloader=core), page=1, page_size=10)
        assert result.success
        assert _data(result)["total"] == 2
        assert _data(result)["items"][0]["title"] == "流浪地球"
        assert _data(result)["items"][0]["season_episode"] == "S01 E01"
        assert core.calls == [(1, 10)]

    def test_keyword_filter(self):
        core = _DownloaderCore([_Row("流浪地球"), _Row("电锯人")])
        result = download_history_list(_ctx(downloader=core), keyword="电锯人")
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["title"] == "电锯人"

    def test_error_returns_failure(self):
        core = _DownloaderCore([])
        core.fail = True
        result = download_history_list(_ctx(downloader=core))
        assert not result.success
        assert "失败" in result.error


class TestPluginTools:
    _PLUGINS = [
        {
            "id": "autogenrss",
            "name": "自动生成RSS",
            "version": "1.0.0",
            "category": "rss",
            "description": "根据订阅自动生成 RSS",
            "enabled": True,
            "is_builtin": True,
            "supports_run": True,
        },
        {
            "id": "demo",
            "name": "演示插件",
            "version": "0.1.0",
            "category": "demo",
            "description": "演示",
            "enabled": False,
            "is_builtin": False,
            "supports_run": False,
        },
    ]

    def test_list_plugins(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_list(_ctx(plugins=svc))
        assert result.success
        assert _data(result)["total"] == 2
        assert _data(result)["items"][0]["id"] == "autogenrss"

    def test_list_enabled_only(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_list(_ctx(plugins=svc), enabled_only=True)
        assert _data(result)["total"] == 1
        assert _data(result)["items"][0]["id"] == "autogenrss"

    def test_plugin_info_with_config(self):
        svc = _PluginService(list(self._PLUGINS), {"autogenrss": {"interval": 60}})
        result = plugin_info(_ctx(plugins=svc), plugin_id="autogenrss")
        assert result.success
        assert _data(result)["name"] == "自动生成RSS"
        assert _data(result)["config"] == {"interval": 60}

    def test_plugin_info_not_found(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_info(_ctx(plugins=svc), plugin_id="missing")
        assert not result.success
        assert "不存在" in result.error

    def test_plugin_run_requires_confirm(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_run(_ctx(plugins=svc), plugin_id="autogenrss")
        assert result.need_confirm
        assert svc.ran == []

    def test_plugin_run_confirmed(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_run(_ctx(plugins=svc), plugin_id="autogenrss", confirmed=True)
        assert result.success
        assert svc.ran == ["autogenrss"]

    def test_plugin_run_not_supported(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_run(_ctx(plugins=svc), plugin_id="demo", confirmed=True)
        assert not result.success
        assert "不支持" in result.error

    def test_plugin_run_not_found(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_run(_ctx(plugins=svc), plugin_id="missing", confirmed=True)
        assert not result.success
        assert "不存在" in result.error

    def test_plugin_enable_requires_confirm(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_enable(_ctx(plugins=svc), plugin_id="autogenrss")
        assert result.need_confirm
        assert svc.enabled == []

    def test_plugin_enable_confirmed(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_enable(_ctx(plugins=svc), plugin_id="autogenrss", confirmed=True)
        assert result.success
        assert svc.enabled == ["autogenrss"]

    def test_plugin_disable_requires_confirm(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_disable(_ctx(plugins=svc), plugin_id="autogenrss")
        assert result.need_confirm
        assert svc.disabled == []

    def test_plugin_disable_confirmed(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_disable(_ctx(plugins=svc), plugin_id="autogenrss", confirmed=True)
        assert result.success
        assert svc.disabled == ["autogenrss"]

    def test_plugin_config_save_requires_confirm(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_config_save(_ctx(plugins=svc), plugin_id="autogenrss", config={"interval": 30})
        assert result.need_confirm
        assert svc.saved == []

    def test_plugin_config_save_confirmed(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_config_save(_ctx(plugins=svc), plugin_id="autogenrss", config={"interval": 30}, confirmed=True)
        assert result.success
        assert svc.saved == [("autogenrss", {"interval": 30})]

    def test_plugin_manage_not_found(self):
        svc = _PluginService(list(self._PLUGINS))
        for tool in (plugin_enable, plugin_disable):
            result = tool(_ctx(plugins=svc), plugin_id="missing", confirmed=True)
            assert not result.success
            assert "不存在" in result.error

    def test_plugin_config_save_invalid_config(self):
        svc = _PluginService(list(self._PLUGINS))
        result = plugin_config_save(_ctx(plugins=svc), plugin_id="autogenrss", config=cast(dict, "bad"), confirmed=True)
        assert not result.success
