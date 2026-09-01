"""飞书消息插件主类.

职责：
- 注册 Feishu 消息渠道（MESSAGE_CLIENT type=feishu），渠道配置统一在消息中心管理
- 注册公开回调端点，接收长连接回环的飞书事件，复用 MessageCommandHandler 处理交互
- 插件启停时同步渠道生命周期（启停交互服务、注册/注销渠道类、启用/禁用渠道记录）
"""

from typing import Any

from app.message.registry import register, unregister
from app.plugin_framework.builtin_plugins._msg_common.callback import InteractiveCallbackMixin
from app.plugin_framework.builtin_plugins._msg_common.channel_lifecycle import (
    disable_channel_record,
    reload_channel_if_needed,
    stop_interactive,
)
from app.plugin_framework.builtin_plugins.feishu.backend.message_client import Feishu
from app.plugin_framework.context import PluginContext

_CHANNEL_TYPE = "feishu"
_CHANNEL_SEARCH_TYPE = "FEISHU"
_CALLBACK_PATH = "callback"


class FeishuPlugin(InteractiveCallbackMixin):
    """飞书消息插件"""

    channel_type = _CHANNEL_TYPE
    channel_search_type = _CHANNEL_SEARCH_TYPE
    callback_path = _CALLBACK_PATH
    # 长连接事件来自本机回环，IP 白名单校验无实际意义，跳过
    check_client_ip = False

    def __init__(self, ctx: PluginContext, app_context: Any = None, message: Any = None):
        self.ctx = ctx
        self._app_context = app_context
        self._message = message or ctx.message

    # ---------- 生命周期 ----------

    def on_enable(self):
        register(Feishu)  # 显式注册飞书渠道类（schema=feishu，供消息中心识别与构建）
        self._register_callback()
        reload_channel_if_needed(self._message, _CHANNEL_TYPE, _CHANNEL_SEARCH_TYPE)
        self.ctx.info("飞书消息插件已启用")

    def on_disable(self):
        stop_interactive(self._message, _CHANNEL_SEARCH_TYPE)
        disable_channel_record(self._message, _CHANNEL_TYPE)
        unregister(_CHANNEL_TYPE)
        self.ctx.info("飞书消息插件已禁用")

    def on_hook(self, event: str, data: dict):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self._reload_channel()

    def run(self):
        """立即运行：发送一条测试消息验证渠道可用"""
        entry = self._message.get_interactive_client(_CHANNEL_SEARCH_TYPE)
        client = entry.get("client") if entry else None
        if not client or not hasattr(client, "send_msg"):
            self.ctx.warn("飞书渠道未配置或未启用，无法发送测试消息")
            return
        state, ret_msg = client.send_msg(title="飞书插件测试", text="这是一条测试消息")
        if state:
            self.ctx.info("飞书测试消息发送成功")
        else:
            self.ctx.error(f"飞书测试消息发送失败: {ret_msg}")

    # ---------- 交互服务 ----------

    def _reload_channel(self):
        """渠道配置变更后重建渠道实例（读取新配置并重启交互服务）"""
        stop_interactive(self._message, _CHANNEL_SEARCH_TYPE)
        reload_channel_if_needed(self._message, _CHANNEL_TYPE, _CHANNEL_SEARCH_TYPE)

    # ---------- 公开回调（回调事件已由 ws_server 解析为 user_id/text）----------

    def _parse_event(self, params: dict) -> tuple[str, str]:
        return str(params.get("user_id") or ""), str(params.get("text") or "")
