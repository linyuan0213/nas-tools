"""消息渠道插件主类."""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
    ensure_channel_record,
)
from app.plugin_framework.builtin_plugins.msg_gotify.backend.message_client import Gotify
from app.plugin_framework.context import PluginContext


class MsgGotifyPlugin:
    """消息渠道插件"""

    def __init__(self, ctx: PluginContext, message: Any = None):
        self.ctx = ctx
        self._message = message or ctx.message

    def on_enable(self):
        register(Gotify)
        ensure_channel_record(self._message, "gotify", "Gotify")
        self._message.reload_by_type("gotify")
        self.ctx.info("消息渠道插件已启用")

    def on_disable(self):
        disable_channel_record(self._message, "gotify")
        unregister("gotify")
        self.ctx.info("消息渠道插件已禁用")
