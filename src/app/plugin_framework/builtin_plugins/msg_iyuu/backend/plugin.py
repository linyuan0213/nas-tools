"""消息渠道插件主类."""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
)
from app.plugin_framework.builtin_plugins.msg_iyuu.backend.message_client import IyuuMsg
from app.plugin_framework.context import PluginContext


class MsgIyuuMsgPlugin:
    """消息渠道插件"""

    def __init__(self, ctx: PluginContext, message: Any = None):
        self.ctx = ctx
        self._message = message or ctx.message

    def on_enable(self):
        register(IyuuMsg)
        self._message.reload_by_type("iyuu")
        self.ctx.info("消息渠道插件已启用")

    def on_disable(self):
        disable_channel_record(self._message, "iyuu")
        unregister("iyuu")
        self.ctx.info("消息渠道插件已禁用")
