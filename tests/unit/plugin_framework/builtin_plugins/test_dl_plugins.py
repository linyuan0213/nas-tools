"""下载器插件（dl_*）测试：manifest、生命周期注册、PT 拦截."""

import json
import os
from unittest.mock import MagicMock, patch

from app.downloader import registry as dl_registry
from app.downloader.pipeline import DownloadPipeline

BASE = "src/app/plugin_framework/builtin_plugins"
DL_PLUGINS = ["dl_thunder", "dl_aria2"]


class TestDlPluginManifest:
    def test_manifests_valid(self):
        for pid in DL_PLUGINS:
            path = os.path.join(BASE, pid, "manifest.json")
            assert os.path.exists(path), f"{pid} 缺少 manifest"
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
            assert m["id"] == pid
            assert m["backend"]["entry"].startswith("backend.plugin:")
            assert m["category"] == "download"


class TestDlPluginLifecycle:
    def test_thunder_registers_and_unregisters(self):
        from app.plugin_framework.builtin_plugins.dl_thunder.backend.plugin import DlThunderPlugin

        plugin = DlThunderPlugin(MagicMock(), downloader=MagicMock())
        with (
            patch("app.plugin_framework.builtin_plugins.dl_thunder.backend.plugin.register") as mock_reg,
            patch("app.plugin_framework.builtin_plugins.dl_thunder.backend.plugin.unregister") as mock_unreg,
        ):
            plugin.on_enable()
            mock_reg.assert_called_once()
            plugin._downloader.refresh_downloaders.assert_called_once()
            plugin.on_disable()
            mock_unreg.assert_called_once_with("thunder")
            plugin._downloader.refresh_downloaders.assert_called()

    def test_aria2_registers_and_unregisters(self):
        from app.plugin_framework.builtin_plugins.dl_aria2.backend.plugin import DlAria2Plugin

        plugin = DlAria2Plugin(MagicMock(), downloader=MagicMock())
        with (
            patch("app.plugin_framework.builtin_plugins.dl_aria2.backend.plugin.register") as mock_reg,
            patch("app.plugin_framework.builtin_plugins.dl_aria2.backend.plugin.unregister") as mock_unreg,
        ):
            plugin.on_enable()
            mock_reg.assert_called_once()
            plugin.on_disable()
            mock_unreg.assert_called_once_with("aria2")

    def test_plugins_declare_supports_pt_false(self):
        from app.plugin_framework.builtin_plugins.dl_aria2.backend.download_client import Aria2
        from app.plugin_framework.builtin_plugins.dl_thunder.backend.download_client import Thunder

        assert Thunder.supports_pt is False
        assert Aria2.supports_pt is False

    def test_core_downloaders_support_pt(self):
        from app.downloader.client.qbittorrent import Qbittorrent
        from app.downloader.client.transmission import Transmission

        assert Qbittorrent.supports_pt is True
        assert Transmission.supports_pt is True


class TestPtInterception:
    def test_is_pt_private_site(self):
        assert DownloadPipeline._is_pt_torrent({"public": False}, b"x") is True
        assert DownloadPipeline._is_pt_torrent({"public": True}, b"x") is False
        assert DownloadPipeline._is_pt_torrent({}, b"x") is False

    def test_is_pt_string_keywords(self):
        magnet = "magnet:?xt=urn:btih:xxx&tr=https://t.example/announce?passkey=abc"
        assert DownloadPipeline._is_pt_torrent({}, magnet) is True
        assert DownloadPipeline._is_pt_torrent({}, "magnet:?xt=urn:btih:xxx&tr=https://t.example/announce") is False
        assert DownloadPipeline._is_pt_torrent({"public": False}, "") is True

    def test_registry_unregister(self):
        dl_registry.unregister("thunder")
        dl_registry.unregister("aria2")
        assert dl_registry.get_client_class("thunder") is None
        assert dl_registry.get_client_class("aria2") is None
