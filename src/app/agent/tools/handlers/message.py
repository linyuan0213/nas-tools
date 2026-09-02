"""消息通知渠道管理工具 handler — 复用 MessageClientService（与 UI 一致）"""

import json
from typing import Any

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext

# 渠道类型配置字段（与 src/app/message/client/* 的真实 config 键一致）
_CHANNEL_HINTS = {
    "telegram": {"token": "Bot Token", "chat_id": "接收 Chat ID"},
    "serverchan": {"sckey": "SendKey"},
    "pushplus": {"token": "Token", "topic": "群组编码(可选)"},
    "wechat": {"corpid": "企业ID", "corpsecret": "应用Secret", "agentid": "应用ID"},
    "bark": {"apikey": "API Key", "server": "自建服务地址(可选)"},
    "ntfy": {"server": "服务器地址", "topic": "主题", "token": "访问Token(可选)"},
    "gotify": {"server": "服务器地址", "token": "应用Token"},
    "chanify": {"server": "服务器地址", "token": "Token"},
    "pushdeer": {"apikey": "API Key", "server": "自建服务地址(可选)"},
    "slack": {"bot_token": "Bot Token", "app_token": "App Token", "channel": "频道"},
    "synologychat": {"webhook_url": "Webhook 地址", "token": "Token(可选)"},
    "iyuu": {"token": "Token"},
    "webhook": {"url": "Webhook 地址", "method": "请求方法(可选)"},
}


def message_client_list(ctx: ToolContext) -> ToolResult:
    """列出已配置的消息通知渠道（隐藏敏感值）"""
    svc = _svc(ctx)
    if not svc:
        return ToolResult(success=False, error="消息客户端服务不可用")
    try:
        data = svc.get_client() or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询消息渠道失败: {e}")
    items = []
    for cid, client in (data or {}).items() if isinstance(data, dict) else []:
        cfg = client.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except (ValueError, TypeError):
                cfg = {}
        items.append(
            {
                "id": cid,
                "name": client.get("name"),
                "type": client.get("type"),
                "enabled": client.get("enabled"),
                "interactive": client.get("interactive"),
                "config": _mask_config(cfg),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def message_channel_types(ctx: ToolContext) -> ToolResult:
    """列出支持的消息渠道类型及所需字段，供新增/配置渠道时使用"""
    return ToolResult(
        success=True,
        data={
            "channels": [
                {"type": ctype, "fields": fields, "hint": _describe_fields(fields)}
                for ctype, fields in _CHANNEL_HINTS.items()
            ]
        },
    )


def message_client_save(
    ctx: ToolContext,
    name: str,
    ctype: str,
    config: dict,
    enabled: bool = True,
    cid: int = 0,
    confirmed: bool = False,
) -> ToolResult:
    """新增或更新消息通知渠道。配置中的密钥/Token 类字段会写库，需确认。"""
    if not name or not ctype:
        return ToolResult(success=False, error="name 与 type 必填")
    if not isinstance(config, dict) or not config:
        return ToolResult(success=False, error="config 必须是非空对象")
    if ctype not in _CHANNEL_HINTS:
        known = ", ".join(_CHANNEL_HINTS)
        return ToolResult(success=False, error=f"不支持的渠道类型: {ctype}（支持: {known}）")
    # 提示缺哪个必填字段但允许仅改开关时使用现有 config
    svc = _svc(ctx)
    action = "更新" if cid else "新增"
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "client_save",
                "ctype": ctype,
                "message": f"{action}消息渠道「{name}」({ctype}) 需确认，配置项: {list(config.keys())}",
            },
        )
    try:
        svc.upsert_client(
            name=name,
            cid=int(cid or 0),
            ctype=ctype,
            config=json.dumps(config, ensure_ascii=False),
            switches="",
            interactive=0,
            enabled=1 if enabled else 0,
            templates="",
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存消息渠道失败: {e}")
    return ToolResult(success=True, data={"message": f"消息渠道「{name}」已保存"})


def message_client_delete(ctx: ToolContext, cid: int, confirmed: bool = False) -> ToolResult:
    """删除消息通知渠道，需确认"""
    svc = _svc(ctx)
    if not svc:
        return ToolResult(success=False, error="消息客户端服务不可用")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "client_delete", "cid": cid, "message": f"删除消息渠道(id={cid})需确认"},
        )
    try:
        svc.delete_client(cid=int(cid))
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"删除消息渠道失败: {e}")
    return ToolResult(success=True, data={"message": f"消息渠道(id={cid})已删除"})


def _svc(ctx: ToolContext) -> Any:
    return getattr(ctx, "message_client_service", None)


def _mask_config(cfg: dict) -> dict:
    return {k: ("***" if v and _is_secret(k) else v) for k, v in cfg.items()}


def _is_secret(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in ("token", "secret", "password", "key", "passwd"))


def _describe_fields(fields: dict) -> str:
    return "；".join(f"{label}" for label in fields.values())


HANDLERS = {
    "message_client_list": message_client_list,
    "message_channel_types": message_channel_types,
    "message_client_save": message_client_save,
    "message_client_delete": message_client_delete,
}
