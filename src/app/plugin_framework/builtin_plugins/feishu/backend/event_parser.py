"""飞书长连接事件解析.

将 lark-oapi 官方 SDK 事件对象解析为 (user_id, text) 二元组，
text 为空表示无需处理。
"""

import json


def parse_im_message(data) -> tuple[str, str]:
    """解析 im.message.receive_v1 事件"""
    event = getattr(data, "event", None)
    if not event:
        return "", ""
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None) if sender else None
    open_id = getattr(sender_id, "open_id", "") if sender_id else ""
    message = getattr(event, "message", None)
    content = {}
    if message and getattr(message, "content", None):
        try:
            content = json.loads(message.content)
        except ValueError:
            content = {}
    return str(open_id), str(content.get("text", "") or "")


def parse_card_action(data) -> tuple[str, str]:
    """解析 card.action.trigger 事件"""
    event = getattr(data, "event", None)
    if not event:
        return "", ""
    action = getattr(event, "action", None)
    value = getattr(action, "value", "") if action else ""
    if isinstance(value, dict):
        text = value.get("value") or value.get("text") or ""
    else:
        text = value
    operator = getattr(event, "operator", None)
    open_id = getattr(operator, "open_id", "") if operator else ""
    return str(open_id), str(text or "")
