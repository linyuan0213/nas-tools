"""系统配置读写工具 handler — 读取配置节点（脱敏）与按白名单写回 config.yaml"""

from typing import Any

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.core.settings import settings
from app.services.system.config import ConfigUpdateService

# 允许 Agent 读写的配置顶层节点（security/database/log 等敏感或环境级节点不开放）
_ALLOWED_SECTIONS = ("app", "media", "pt", "subscribe", "laboratory", "agent")

# 字段名含这些关键字的叶子视为敏感：读取时脱敏、禁止写入
_SECRET_HINTS = (
    "password",
    "passwd",
    "api_key",
    "apikey",
    "token",
    "secret",
    "cookie",
    "jwt",
    "ssl_key",
    "admin_token",
)


def config_get(ctx: ToolContext, section: str = "") -> ToolResult:
    """读取系统配置节点（敏感字段已脱敏为 ***）。section 为空时列出可读节点概览。"""
    section = (section or "").strip()
    try:
        data = settings.get() or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取配置失败: {e}")

    if not section:
        overview = {}
        for sec in _ALLOWED_SECTIONS:
            node = data.get(sec)
            if isinstance(node, dict):
                overview[sec] = list(node.keys())
        return ToolResult(success=True, data={"nodes": overview})

    if section not in _ALLOWED_SECTIONS:
        return ToolResult(
            success=False,
            error=f"不允许读取该节点: {section}（可读节点: {', '.join(_ALLOWED_SECTIONS)}）",
        )
    node = data.get(section)
    if node is None:
        return ToolResult(success=False, error=f"配置节点不存在: {section}")
    return ToolResult(success=True, data={section: _mask(node)})


def config_set(ctx: ToolContext, config: dict, confirmed: bool = False) -> ToolResult:
    """按扁平点路径写回系统配置（如 {"media.tmdb_language": "zh"}），需确认。"""
    if not isinstance(config, dict) or not config:
        return ToolResult(success=False, error="config 参数必须是非空对象（扁平键→值）")

    # 校验：节点白名单 + 键存在 + 非敏感字段
    invalid, sensitive, unknown = [], [], []
    for key in config:
        top = (key or "").split(".", 1)[0]
        if top not in _ALLOWED_SECTIONS:
            invalid.append(key)
            continue
        if any(h in key.lower() for h in _SECRET_HINTS):
            sensitive.append(key)
            continue
        if not _is_known_leaf(key):
            unknown.append(key)
    if invalid or sensitive or unknown:
        msgs = []
        if invalid:
            msgs.append(f"不允许修改的节点: {', '.join(invalid)}")
        if sensitive:
            msgs.append(f"敏感字段禁止通过 Agent 修改: {', '.join(sensitive)}")
        if unknown:
            msgs.append(f"未知配置键: {', '.join(unknown)}")
        return ToolResult(success=False, error="；".join(msgs))

    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "config_set", "config": config, "message": "写入以下系统配置需确认: " + str(config)},
        )
    try:
        result = ConfigUpdateService.update_config(config)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存配置失败: {e}")
    if not getattr(result, "success", True):
        return ToolResult(success=False, error="保存配置失败")
    return ToolResult(success=True, data={"config": config, "message": "系统配置已更新并重载"})


def _mask(node: Any) -> Any:
    """递归脱敏：键名含敏感关键字的值替换为 ***"""
    if isinstance(node, dict):
        return {
            k: "***" if isinstance(v, (str, int, float, bool)) and v not in ("", None) and _is_secret(k) else _mask(v)
            for k, v in node.items()
        }
    return node


def _is_secret(key: str) -> bool:
    return any(h in key.lower() for h in _SECRET_HINTS)


def _is_known_leaf(key: str) -> bool:
    """判断扁平键是否为现有配置中的真实叶子（避免写入拼写错误的键）"""
    try:
        data = settings.get() or {}
    except Exception:  # noqa: BLE001
        return False
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return isinstance(cur, dict) and parts[-1] in cur


HANDLERS = {
    "config_get": config_get,
    "config_set": config_set,
}
