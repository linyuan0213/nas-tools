"""AutoGenRss Plugin v2."""

from threading import Event
from typing import Any

import log
from app.db.repositories.site_repository import SiteRepository
from app.plugin_framework.builtin_plugins.autogenrss.backend.generator import (
    RssGenEngine,
)
from app.plugin_framework.builtin_plugins.autogenrss.backend.registry import (
    RssHandlerRegistry,
)
from app.plugin_framework.builtin_plugins.autogenrss.backend.rss_config_store import (
    RssConfigStore,
)
from app.plugin_framework.context import PluginContext
from app.sites.site_cache import SiteCache


class AutoGenRssPlugin:
    """RSS自动生成插件"""

    def __init__(
        self,
        ctx: PluginContext,
        site_cache: SiteCache,
        site_repo: SiteRepository | None = None,
        siteconf: Any | None = None,
    ):
        self.ctx = ctx
        self._config_store = RssConfigStore(ctx, site_engine=self.ctx.site_engine)
        self._registry: RssHandlerRegistry | None = None
        self._engine: RssGenEngine | None = None
        self._site_repo = site_repo or SiteRepository()
        self._site_cache = site_cache
        self._event = Event()
        self._siteconf = siteconf

    def _get_config(self):
        return self.ctx.get_config() or {}

    def _get_rate_limiter(self):
        engine = self.ctx.site_engine
        rate_limiter = getattr(engine, "site_limiter", None)
        return rate_limiter.engine if rate_limiter else None

    def on_enable(self):
        self.ctx.info("RSS自动生成插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("RSS自动生成插件已禁用")
        self._event.set()
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed" and data.get("plugin_id") == self.ctx.plugin_id:
            self.ctx.info("配置已变更，重载服务")
            self._stop_service()
            self._start_service()

    def run(self):
        """立即运行"""
        self.ctx.info("手动触发RSS生成")
        self._do_gen_rss(manual=True)

    def _start_service(self):
        config = self._get_config()
        enabled = config.get("enabled", False)
        cron = config.get("cron")

        if not enabled:
            return

        self._event.clear()
        rss_configs = self._config_store.load()
        self._registry = RssHandlerRegistry(
            self.ctx,
            self._get_rate_limiter(),
            self.ctx.site_engine,
            rss_configs,
            self._site_repo,
            self._site_cache,
        )
        self._registry.load()
        self._engine = RssGenEngine(
            self.ctx,
            self._registry,
            site_cache=self._site_cache,
            site_repo=self._site_repo,
            site_engine=self.ctx.site_engine,
            event=self._event,
        )
        self.ctx.debug(f"加载RSS生成处理器：{len(self._registry)} 个")

        if cron:
            self.ctx.info(f"同步服务启动，周期：{cron}")
            self.ctx.schedule_cron("gen_rss", self._do_gen_rss, cron=str(cron))

    def _stop_service(self):
        try:
            self.ctx.remove_schedule("gen_rss")
            self.ctx.remove_schedule("gen_rss_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")

    def _do_gen_rss(self, manual=False):
        if not self._get_config().get("enabled") and not manual:
            return
        if not self._engine:
            return
        self._engine.run(self._get_config())
