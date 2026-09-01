"""
AutoRestart Plugin v2
定时自动重启 Nexus Media 服务
"""

import os
import signal
import time

import log
from app.plugin_framework.context import PluginContext


class AutoRestartPlugin:
    """自动重启插件"""

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        self.ctx.info("自动重启插件已启用")
        self._start_service()

    def on_disable(self):
        self.ctx.info("自动重启插件已禁用")
        self._stop_service()

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self._stop_service()
                self._start_service()

    def run(self):
        """立即运行重启"""
        self.ctx.info("手动触发重启")
        self._do_restart()

    def _start_service(self):
        config = self._get_config()
        enabled = config.get("enabled", False)
        cron = config.get("cron")

        if not enabled:
            return

        if enabled and cron:
            self.ctx.info(f"定时重启服务启动，周期：{cron}")
            self.ctx.schedule_cron("restart", self._do_restart, cron=str(cron))

    def _stop_service(self):
        try:
            self.ctx.remove_schedule("restart")
            self.ctx.remove_schedule("restart_once")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Plugin]忽略异常: {e}")

    def _do_restart(self):
        config = self._get_config()
        delay = int(config.get("delay", 0))
        notify = config.get("notify", False)

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        self.ctx.info(f"当前时间 {now} 开始重启流程")

        if notify:
            self.ctx.notify(
                title="[系统重启通知]",
                text=f"Nexus Media将在 {delay} 秒后重启\n时间：{now}",
            )

        if delay > 0:
            self.ctx.info(f"等待 {delay} 秒后重启...")
            time.sleep(delay)

        try:
            self.ctx.info("执行重启...")
            pid = os.getpid()
            self.ctx.info(f"当前进程ID: {pid}")
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            self.ctx.error(f"重启失败：{e}")
            if notify:
                self.ctx.notify(
                    title="[系统重启失败]",
                    text=f"Nexus Media重启失败：{e}\n时间：{now}",
                )
