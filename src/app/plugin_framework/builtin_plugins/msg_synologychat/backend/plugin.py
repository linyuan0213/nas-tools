"""Synology Chat 消息渠道插件主类."""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.callback import InteractiveCallbackMixin
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
    reload_channel_if_needed,
    stop_interactive,
)
from app.plugin_framework.builtin_plugins.msg_synologychat.backend.event_parser import parse_event
from app.plugin_framework.builtin_plugins.msg_synologychat.backend.message_client import SynologyChat
from app.plugin_framework.context import PluginContext

_CHANNEL_TYPE = "synologychat"
_CHANNEL_SEARCH_TYPE = "SYNOLOGY"
_CALLBACK_PATH = "callback"


class MsgSynologychatPlugin(InteractiveCallbackMixin):
    """Synology Chat 消息渠道插件"""

    channel_type = _CHANNEL_TYPE
    channel_search_type = _CHANNEL_SEARCH_TYPE
    callback_path = _CALLBACK_PATH

    def __init__(self, ctx: PluginContext, app_context: Any = None, message: Any = None):
        self.ctx = ctx
        self._app_context = app_context
        self._message = message or ctx.message

    def on_enable(self):
        register(SynologyChat)
        self._register_callback()
        reload_channel_if_needed(self._message, _CHANNEL_TYPE, _CHANNEL_SEARCH_TYPE)
        self.ctx.info("Synology Chat 消息渠道插件已启用")

    def on_disable(self):
        stop_interactive(self._message, _CHANNEL_SEARCH_TYPE)
        disable_channel_record(self._message, _CHANNEL_TYPE)
        unregister(_CHANNEL_TYPE)
        self.ctx.info("Synology Chat 消息渠道插件已禁用")

    def _parse_event(self, params: dict) -> tuple[str, str]:
        return parse_event(params)
