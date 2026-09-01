"""
LibraryScraper Plugin v2
定时对媒体库进行刮削
"""

from threading import Event

import log
from app.media.scraper import Scraper
from app.plugin_framework.context import PluginContext


class LibraryScraperPlugin:
    """媒体库刮削插件"""

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx
        self._scraper = Scraper(media_service=ctx.media_service)
        self._event = Event()

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("媒体库刮削插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("媒体库刮削插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()
        elif event == "media.scraped":
            event_info = data or {}
            path = event_info.get("path")
            force = event_info.get("force")
            if path:
                mode = "force_all" if force else "no_force"
                self._scraper.folder_scraper(path, mode=mode)

    def run(self):
        """立即运行刮削"""
        self.ctx.info("手动触发媒体库刮削")
        self._do_scrape()

    def _start_service(self):
        config = self._get_config()
        cron = config.get("cron")

        if not cron:
            return

        if cron:
            self.ctx.info(f"刮削服务启动，周期：{cron}")
            self.ctx.schedule_cron("scrape", self._do_scrape, cron=str(cron))

    def _stop_service(self):
        self._event.set()
        try:
            self.ctx.remove_schedule("scrape")
            self.ctx.remove_schedule("scrape_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")
        self._event.clear()

    def _do_scrape(self):
        config = self._get_config()
        scraper_path = config.get("scraper_path", [])
        exclude_path = config.get("exclude_path")
        mode = config.get("mode", "no_force")

        if isinstance(scraper_path, str):
            scraper_path = scraper_path.split("\n")

        self.ctx.info(f"开始刮削媒体库：{scraper_path} ...")
        for path in scraper_path:
            if not path:
                continue
            if self._event.is_set():
                self.ctx.info("媒体库刮削服务停止")
                return
            self._scraper.folder_scraper(path=path, exclude_path=exclude_path, mode=mode)
        self.ctx.info("媒体库刮削完成")
