"""Synology Chat 交互事件解析."""


def parse_event(update: dict) -> tuple[str, str]:
    """解析 Synology Chat 事件负载，返回 (user_id, text)"""
    return str(update.get("user_id", "") or ""), str(update.get("text", "") or "")
