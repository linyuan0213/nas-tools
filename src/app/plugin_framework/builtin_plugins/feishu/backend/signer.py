"""飞书消息签名工具.

- 自定义机器人 Webhook 加签：timestamp + secret 生成 sign 头
- 事件订阅（Webhook 模式）校验使用同款签名算法
"""

import base64
import hashlib
import hmac


def gen_sign(secret: str, timestamp: int | str) -> str:
    """生成飞书机器人加签值.

    :param secret: 机器人安全设置中的签名密钥
    :param timestamp: Unix 秒级时间戳
    """
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")
