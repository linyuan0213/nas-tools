"""Slack 交互事件解析."""



def parse_event(update: dict) -> tuple[str, str]:
    """解析 Slack 事件负载，返回 (user_id, text)"""
    user = update.get("user", "")
    if isinstance(user, dict):
        user = user.get("id", "")
    text = update.get("text", "")
    if not text:
        text = update.get("command", "")
    return str(user), str(text or "")
