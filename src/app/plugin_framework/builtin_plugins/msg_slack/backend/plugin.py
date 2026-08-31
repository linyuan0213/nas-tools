"""Slack 消息渠道插件主类."""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.callback import InteractiveCallbackMixin
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
    ensure_channel_record,
    stop_interactive,
)
from app.plugin_framework.builtin_plugins.msg_slack.backend.event_parser import parse_event
from app.plugin_framework.builtin_plugins.msg_slack.backend.message_client import Slack
from app.plugin_framework.context import PluginContext

_CHANNEL_TYPE = "slack"
_CHANNEL_SEARCH_TYPE = "SLACK"
_CALLBACK_PATH = "callback"


class MsgSlackPlugin(InteractiveCallbackMixin):
    """Slack 消息渠道插件"""

    channel_type = _CHANNEL_TYPE
    channel_search_type = _CHANNEL_SEARCH_TYPE
    callback_path = _CALLBACK_PATH

    def __init__(self, ctx: PluginContext, app_context: Any = None, message: Any = None):
        self.ctx = ctx
        self._app_context = app_context
        self._message = message or ctx.message

    def on_enable(self):
        register(Slack)
        self._register_callback()
        ensure_channel_record(self._message, _CHANNEL_TYPE, "Slack", interactive=1)
        self._message.reload_by_type(_CHANNEL_TYPE)
        self.ctx.info("Slack 消息渠道插件已启用")

    def on_disable(self):
        stop_interactive(self._message, _CHANNEL_SEARCH_TYPE)
        disable_channel_record(self._message, _CHANNEL_TYPE)
        unregister(_CHANNEL_TYPE)
        self.ctx.info("Slack 消息渠道插件已禁用")

    def _pre_handle(self, params: dict) -> dict | None:
        if params.get("type") == "url_verification":
            return {"challenge": params.get("challenge")}
        return None

    def _parse_event(self, params: dict) -> tuple[str, str]:
        return parse_event(params)
