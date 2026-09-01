"""钉钉 Stream 交互事件解析.

将 ChatbotMessage 解析为 (user_id, text) 二元组（在渠道类 Stream handler 内调用）。
"""

from dingtalk_stream import ChatbotMessage


def parse_chatbot_message(callback_data: dict) -> tuple[str, str]:
    """解析钉钉机器人回调消息负载，返回 (user_id, text)"""
    try:
        msg = ChatbotMessage.from_dict(callback_data)
    except Exception:  # noqa: BLE001
        return "", ""
    text = msg.text.content if msg.text else ""
    return str(msg.sender_staff_id or ""), str(text or "")
