"""交互渠道插件公开回调公共逻辑.

统一三个交互插件（feishu/msg_slack/msg_synologychat）的
_on_callback / _verify_apikey / _verify_client_ip 实现，
避免重复并保证安全校验策略一致。
"""


from typing import Any

import log
from app.infrastructure.security import SecurityChecker
from app.services.message_handler_factory import get_message_command_handler


class InteractiveCallbackMixin:
    """交互渠道公开回调基类.

    子类需提供：_app_context / _message / ctx（或按需覆写 _verify_apikey）。
    """

    # 子类声明
    channel_type: str = ""
    channel_search_type: str = ""
    callback_path: str = "callback"
    # 是否启用来源 IP 白名单校验（交互渠道默认开启）
    check_client_ip: bool = True

    # 由插件 __init__ 注入
    ctx: Any = None
    _app_context: Any = None
    _message: Any = None

    def _register_callback(self) -> None:
        self.ctx.register_public_webhook(self.callback_path, self._on_callback)

    def _on_callback(self, params: dict) -> dict:
        """公开回调入口：apikey 校验 → 事件预处理 → IP 校验 → 解析 → 命令处理"""
        if not self._verify_apikey(params.get("apikey")):
            return {"code": -1, "msg": "apikey 无效"}
        pre = self._pre_handle(params)
        if pre is not None:
            return pre
        if self.check_client_ip and not self._verify_client_ip(params.get("_client_ip", "")):
            return {"code": -1, "msg": "IP 不允许"}
        user_id, text = self._parse_event(params)
        if not text:
            return {"code": 0, "msg": "success"}
        log.info(f"[{self.channel_type}]收到消息: user={user_id}, text={text[:60]}...")
        try:
            handler = get_message_command_handler(self._app_context, self._message)
            handler.handle_message_job(msg=text, in_from=self.channel_search_type, user_id=user_id)
        except Exception as e:  # noqa: BLE001
            log.error(f"[{self.channel_type}]消息处理失败: {e}")
            return {"code": -1, "msg": f"处理失败: {e!s}"}
        return {"code": 0, "msg": "success"}

    def _pre_handle(self, params: dict) -> dict | None:
        """事件预处理钩子：返回 dict 则短路（如 Slack url_verification）"""
        return None

    def _parse_event(self, params: dict) -> tuple[str, str]:
        """子类覆写：渠道事件 → (user_id, text)"""
        raise NotImplementedError

    def _verify_apikey(self, apikey: str | None) -> bool:
        if not apikey:
            return False
        try:
            key = self._app_context.apikey_service.validate_key(apikey)
            return key is not None
        except Exception:  # noqa: BLE001
            return False

    def _verify_client_ip(self, client_ip: str) -> bool:
        """按渠道配置的 IP 白名单校验来源（默认放行）"""
        entry = self._message.get_interactive_client(self.channel_search_type)
        client = entry.get("client") if entry else None
        if client and hasattr(client, "get_webhook_allow_ip"):
            allow = client.get_webhook_allow_ip()
        else:
            allow = {"ipv4": "0.0.0.0/0", "ipv6": "::/0"}
        if not SecurityChecker.allow_access(allow, client_ip):
            log.warn(f"[{self.channel_type}]回调 IP 白名单拒绝: {client_ip}")
            return False
        return True
