"""系统日志查询工具 handler — 默认读 LOG_BUFFER；hours 指定时检索磁盘日志文件（含轮转）"""

import log
from app.agent.sanitize import sanitize
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext
from app.services.log_search_service import LogSearchService

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_ERROR_LEVELS = ("ERROR", "WARNING")


def system_logs(
    ctx: ToolContext,
    source: str = "",
    level: str = "",
    keyword: str = "",
    limit: int = 50,
    hours: int | None = None,
) -> ToolResult:
    """查询系统运行日志，脱敏后返回，错误/警告优先。

    hours 为空时读内存缓冲（最近 2000 条，最快）；hours 指定时检索磁盘日志文件
    （含轮转）最近 N 小时内的记录，用于排查历史/跨天问题。
    磁盘检索耗时与 hours 正相关（24h 约 10s、72h 约 20s+），能先缩小时间范围时
    请用较小的 hours（如 1/6/24），不要为了保险一次扫数天。
    """
    try:
        limit = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        limit = 50

    if hours is not None:
        return _search_disk_logs(source=source, level=level, keyword=keyword, limit=limit, hours=hours)
    return _read_buffer(source=source, level=level, keyword=keyword, limit=limit)


def _read_buffer(source: str, level: str, keyword: str, limit: int) -> ToolResult:
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

    return _to_result(selected)


def _search_disk_logs(source: str, level: str, keyword: str, limit: int, hours: int) -> ToolResult:
    """检索磁盘日志文件最近 N 小时（复用 UI 的 LogSearchService，含轮转文件与旧文件跳过）"""
    try:
        hours = max(1, min(int(hours), 168))
    except (TypeError, ValueError):
        return ToolResult(success=False, error="hours 参数无效")
    try:
        result = LogSearchService().search(
            keyword=keyword or None,
            level=level or None,
            source=source or None,
            page=1,
            page_size=limit,
            hours=hours,
        )
    except Exception as e:
        return ToolResult(success=False, error=f"磁盘日志检索失败: {e}")

    items = [
        {
            "time": item.get("time", ""),
            "level": item.get("level", ""),
            "source": item.get("source", ""),
            "message": sanitize(item.get("text", "")),
        }
        for item in (result.get("items") or [])
    ]
    return ToolResult(success=True, data={"total": result.get("total", 0), "logs": items})


def _to_result(items: list) -> ToolResult:
    data = [
        {
            "time": item.get("time", ""),
            "level": item.get("level", ""),
            "source": item.get("source", ""),
            "message": sanitize(item.get("text", "")),
        }
        for item in items
    ]
    return ToolResult(success=True, data={"total": len(data), "logs": data})
