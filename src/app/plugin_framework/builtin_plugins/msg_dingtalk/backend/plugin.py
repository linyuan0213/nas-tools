"""钉钉消息渠道插件主类."""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.callback import InteractiveCallbackMixin
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
    reload_channel_if_needed,
    stop_interactive,
)
from app.plugin_framework.builtin_plugins.msg_dingtalk.backend.message_client import DingTalk
from app.plugin_framework.context import PluginContext

_CHANNEL_TYPE = "dingtalk"
_CHANNEL_SEARCH_TYPE = "DINGTALK"
_CALLBACK_PATH = "callback"


class MsgDingtalkPlugin(InteractiveCallbackMixin):
    """钉钉消息渠道插件"""

    channel_type = _CHANNEL_TYPE
    channel_search_type = _CHANNEL_SEARCH_TYPE
    callback_path = _CALLBACK_PATH
    # Stream 长连接事件来自本机回环，IP 白名单校验无实际意义
    check_client_ip = False

    def __init__(self, ctx: PluginContext, app_context: Any = None, message: Any = None):
        self.ctx = ctx
        self._app_context = app_context
        self._message = message or ctx.message

    def on_enable(self):
        register(DingTalk)
        self._register_callback()
        reload_channel_if_needed(self._message, _CHANNEL_TYPE, _CHANNEL_SEARCH_TYPE)
        self.ctx.info("钉钉消息渠道插件已启用")

    def on_disable(self):
        stop_interactive(self._message, _CHANNEL_SEARCH_TYPE)
        disable_channel_record(self._message, _CHANNEL_TYPE)
        unregister(_CHANNEL_TYPE)
        self.ctx.info("钉钉消息渠道插件已禁用")

    def _parse_event(self, params: dict) -> tuple[str, str]:
        return str(params.get("user_id") or ""), str(params.get("text") or "")
