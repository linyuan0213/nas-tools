"""Aria2 下载器插件主类."""

from typing import Any

from app.downloader.registry import register, unregister
from app.plugin_framework.builtin_plugins._dl_common.downloader_lifecycle import disable_downloader_records
from app.plugin_framework.builtin_plugins.dl_aria2.backend.download_client import Aria2
from app.plugin_framework.context import PluginContext


class DlAria2Plugin:
    """Aria2 下载器插件（不支持 PT 私有站点种子）"""

    def __init__(self, ctx: PluginContext, downloader: Any = None):
        self.ctx = ctx
        self._downloader = downloader

    def on_enable(self):
        register(Aria2)
        if self._downloader is not None:
            self._downloader.refresh_downloaders()
        self.ctx.info("Aria2 下载器插件已启用")

    def on_disable(self):
        disable_downloader_records("aria2")
        unregister("aria2")
        if self._downloader is not None:
            self._downloader.refresh_downloaders()
        self.ctx.info("Aria2 下载器插件已禁用")
