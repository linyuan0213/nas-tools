from datetime import datetime
from typing import Any

import log
from app.infrastructure.rate_limiter import RateLimitEngine
from app.plugin_framework.builtin_plugins.autosignin.backend.registry import HandlerRegistry
from app.plugin_framework.builtin_plugins.autosignin.backend.signer import SigninEngine
from app.plugin_framework.builtin_plugins.autosignin.backend.signin_config_store import SigninConfigStore
from app.plugin_framework.context import PluginContext
from app.utils.json_utils import JsonUtils


class AutoSignInPlugin:
    def __init__(
        self,
        ctx: PluginContext,
        site_cache: Any,
        agent_service: Any | None = None,
        rate_limit_engine: RateLimitEngine | None = None,
    ):
        self.ctx = ctx
        self._config_store = SigninConfigStore(ctx, site_engine=self.ctx.site_engine)
        self._registry: Any = None
        self._engine: Any = None
        self._rate_limit_engine = rate_limit_engine or RateLimitEngine()
        self._site_cache = site_cache
        self._agent_service = agent_service

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("站点自动签到插件已启用")
        signin_configs = self._config_store.load()
        self._registry = HandlerRegistry(
            self.ctx,
            self._rate_limit_engine,
            self.ctx.site_engine,
            signin_configs,
            self._agent_service,
        )
        self._registry.load()
        self._engine = SigninEngine(
            self.ctx,
            self._registry,
            site_cache=self._site_cache,
            site_engine=self.ctx.site_engine,
        )
        self._start_service()
        self.ctx.register_message_command(cmd="/signin", desc="站点签到", func=self._handle_signin_command)

    def on_disable(self):
        self.ctx.info("站点自动签到插件已禁用")
        self._stop_service()
        self.ctx.unregister_message_command("/signin")

    def _handle_signin_command(self, msg, in_from, user_id, user_name):
        self.ctx.info(f"收到签到命令: user={user_name}, msg={msg}")
        self.run()
        self.ctx._message.send_channel_msg(
            channel=in_from, title="站点签到", text="签到任务已触发，请稍后查看签到结果", user_id=user_id
        )

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        self.ctx.info("手动触发站点签到")
        if not self._get_config().get("enabled"):
            return
        self._engine.run(
            self._get_config(),
            get_history=self._get_history,
            update_history=self._update_history,
            delete_history=self._delete_history,
        )

    def _start_service(self):
        config = self._get_config()
        enabled = config.get("enabled", False)
        cron = config.get("cron")
        clean = config.get("clean", False)

        if not enabled:
            return

        self._registry.load()
        self.ctx.debug(f"加载站点签到处理器：{len(self._registry)} 个")

        if clean:
            self._delete_history(datetime.today().strftime("%Y-%m-%d"))
            self.ctx.set_config("clean", False)

        if cron:
            self.ctx.info(f"定时签到服务启动，周期：{cron}")
            self.ctx.schedule_cron("signin", self.run, cron=str(cron))

    def _stop_service(self):
        try:
            self.ctx.remove_schedule("signin")
            self.ctx.remove_schedule("signin_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")

    def _load_history(self):
        content = self.ctx.read_data("history.json")
        if content:
            try:
                return JsonUtils.loads(content)
            except Exception as e:  # noqa: BLE001
                log.debug(f"[Plugin]忽略异常: {e}")
        return {}

    def _save_history(self, data):
        self.ctx.write_data("history.json", JsonUtils.dumps(data, ensure_ascii=False, indent=2))

    def _get_history(self, key=None):
        data = self._load_history()
        if key:
            return data.get(key)
        return data

    def _update_history(self, key, value):
        data = self._load_history()
        data[key] = value
        self._save_history(data)

    def _delete_history(self, key):
        data = self._load_history()
        if key in data:
            del data[key]
            self._save_history(data)
