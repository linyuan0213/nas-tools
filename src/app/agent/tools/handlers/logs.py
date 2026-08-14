"""系统日志查询工具 handler — 读 LOG_BUFFER，脱敏后返回，错误/警告优先"""

import log
from app.agent.sanitize import sanitize
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_ERROR_LEVELS = ("ERROR", "WARNING")


def system_logs(
    ctx: ToolContext,
    source: str = "",
    level: str = "",
    keyword: str = "",
    limit: int = 50,
) -> ToolResult:
    """查询系统运行日志（最近缓冲），脱敏后返回，错误/警告优先。"""
    try:
        logs, _ = log.LOG_BUFFER.get_logs(source=(source or "").strip() or None)
    except Exception as e:
        return ToolResult(success=False, error=f"读取日志失败: {e}")

    lv = (level or "").strip().upper()
    if lv and lv in _LOG_LEVELS:
        logs = [lg for lg in logs if lg.get("level") == lv]

    kw = (keyword or "").strip().lower()
    if kw:
        logs = [lg for lg in logs if kw in (lg.get("text") or "").lower()]

    try:
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        limit = 50

    # 错误/警告优先：未指定级别时最近的错误始终包含，其余补充普通日志至 limit
    if lv:
        selected = logs[-limit:]
    else:
        errors = [lg for lg in logs if lg.get("level") in _ERROR_LEVELS]
        if errors:
            selected = errors[-limit:]
            fill = limit - len(selected)
            if fill > 0:
                selected = logs[-fill:] + selected
        else:
            selected = logs[-limit:]

    items = [
        {
            "time": lg.get("time", ""),
            "level": lg.get("level", ""),
            "source": lg.get("source", ""),
            "message": sanitize(lg.get("text", "")),
        }
        for lg in selected
    ]
    return ToolResult(success=True, data={"total": len(items), "logs": items})
