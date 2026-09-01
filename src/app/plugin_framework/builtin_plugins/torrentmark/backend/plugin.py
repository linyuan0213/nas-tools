"""
TorrentMark Plugin v2
标记种子是否是PT
"""

from threading import Event
from typing import Any

import log
from app.plugin_framework.context import PluginContext


class TorrentMarkPlugin:
    """种子标记插件"""

    def __init__(self, ctx: PluginContext, downloader: Any):
        self.ctx = ctx
        self._downloader = downloader
        self._event = Event()

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("种子标记插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("种子标记插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行标记"""
        self.ctx.info("手动触发种子标记")
        self._do_mark(manual=True)

    def _start_service(self):
        config = self._get_config()
        enable = config.get("enable", False)
        cron = config.get("cron")

        if not enable:
            return

        if cron:
            self.ctx.info(f"标记服务启动，周期：{cron}")
            self.ctx.schedule_cron("mark", self._do_mark, cron=str(cron))

    def _stop_service(self):
        self._event.set()
        try:
            self.ctx.remove_schedule("mark")
            self.ctx.remove_schedule("mark_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")
        self._event.clear()

    def _do_mark(self, manual=False):
        config = self._get_config()
        enable = config.get("enable", False)
        downloaders = config.get("downloaders", [])

        if not manual and (not enable or not downloaders):
            self.ctx.warn("标记服务未启用或未配置下载器")
            return

        for downloader_id in downloaders:
            if self._event.is_set():
                self.ctx.info("标记服务停止")
                return

            self.ctx.info(f"开始扫描下载器：{downloader_id} ...")
            torrents = self._downloader.get_completed_torrents(downloader_id=downloader_id)
            if not torrents:
                self.ctx.info(f"下载器 {downloader_id} 没有已完成种子")
                continue

            self.ctx.info(f"下载器 {downloader_id} 已完成种子数：{len(torrents)}")
            for torrent in torrents:
                if self._event.is_set():
                    self.ctx.info("标记服务停止")
                    return

                hash_str = torrent.id
                torrent_tags = set(torrent.labels)
                trackers = self._downloader.get_torrent_trackers(hash_str, downloader_id=downloader_id) or []
                pt_flag = self._is_pt(trackers)
                torrent_tags.discard("")

                if pt_flag:
                    torrent_tags.discard("BT")
                    torrent_tags.add("PT")
                else:
                    torrent_tags.add("BT")
                    torrent_tags.discard("PT")

                self._downloader.set_torrents_tag(downloader_id=downloader_id, ids=hash_str, tags=list(torrent_tags))

        self.ctx.info("标记任务执行完成")

    @staticmethod
    def _is_pt(trackers: list[str]):
        if not trackers:
            return False
        keywords = ["secure=", "passkey=", "totheglory", "credential=", "tracker.zhuque.in", "announce?uid="]
        return any(any(keyword in tracker for keyword in keywords) for tracker in trackers)
