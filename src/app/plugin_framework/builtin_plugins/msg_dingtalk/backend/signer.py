"""钉钉机器人签名工具（自定义机器人加签，与飞书同款 HMAC-SHA256 算法）"""

import base64
import hashlib
import hmac


def gen_sign(secret: str, timestamp: int | str) -> str:
    """生成钉钉机器人加签值"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")
