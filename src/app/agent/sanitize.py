"""脱敏工具 — 隐藏 api_key / sk- / cookie 等敏感信息（日志安全）"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_.\-]{8,}|"
    r"api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']|"
    r"cookie[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"'])",
    re.I,
)

# 结构化对象中视为敏感的直接键名（命中即整值打码）
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "apikey",
    "api_key",
    "api-key",
    "token",
    "secret",
    "password",
    "passwd",
    "passkey",
    "cookie",
    "jwt",
    "ssl_key",
    "admin_token",
    "authorization",
    "bearer",
    "access_key",
    "accesskey",
    "private_key",
    "client_secret",
    "refresh_token",
    "sign",
)
_SENSITIVE_VALUE_RE = re.compile(r"sk-[A-Za-z0-9_.\-]{8,}")


def sanitize(text: str) -> str:
    """脱敏：隐藏 api_key / sk- / cookie 等敏感信息"""
    if not text:
        return text
    return _SECRET_RE.sub(lambda m: m.group(0)[:6] + "***" + m.group(0)[-2:], text)


def is_secret_key(key: str, extra_hints: Sequence[str] = ()) -> bool:
    """判断键名是否为敏感键（命中内置提示词或调用方补充提示词）"""
    low = str(key).lower()
    return any(hint in low for hint in _SECRET_KEY_HINTS) or any(hint in low for hint in extra_hints)


def mask_config_values(cfg: Mapping[str, Any], extra_hints: Sequence[str] = ()) -> dict[str, Any]:
    """浅层脱敏（各配置类 handler 输出展示用）：键名命中敏感提示词的标量值替换为 ***"""
    return {k: ("***" if v not in ("", None) and is_secret_key(k, extra_hints) else v) for k, v in cfg.items()}


def mask_tree(node: Any, extra_hints: Sequence[str] = ()) -> Any:
    """递归脱敏任意结构（用于整棵配置树读取），键名命中敏感提示词的值替换为 ***"""
    if isinstance(node, dict):
        return {
            k: ("***" if v not in ("", None) and is_secret_key(k, extra_hints) else mask_tree(v, extra_hints))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [mask_tree(item, extra_hints) for item in node]
    return node


def sanitize_dict(obj: Any) -> Any:
    """递归脱敏结构化对象（用于工具参数/结果入库与回传模型前的副本，不改原对象）"""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for key, value in obj.items():
            if is_secret_key(key) and value not in (None, ""):
                cleaned[key] = "***"
            else:
                cleaned[key] = sanitize_dict(value)
        return cleaned
    if isinstance(obj, list):
        return [sanitize_dict(item) for item in obj]
    if isinstance(obj, str):
        if _SENSITIVE_VALUE_RE.search(obj):
            return _SENSITIVE_VALUE_RE.sub("***", obj)
        return sanitize(obj)
    return obj
