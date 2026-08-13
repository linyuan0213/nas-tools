"""脱敏工具 — 隐藏 api_key / sk- / cookie 等敏感信息（日志安全）"""

import re

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_.\-]{8,}|"
    r"api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']|"
    r"cookie[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"'])",
    re.I,
)


def sanitize(text: str) -> str:
    """脱敏：隐藏 api_key / sk- / cookie 等敏感信息"""
    if not text:
        return text
    return _SECRET_RE.sub(lambda m: m.group(0)[:6] + "***" + m.group(0)[-2:], text)
