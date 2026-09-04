"""刷流工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def brush_status(ctx: ToolContext) -> ToolResult:
    """查询刷流任务状态"""
    try:
        tasks = ctx.brush_service.get_tasks()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询刷流任务失败: {e}")
    if not isinstance(tasks, (list, dict)):
        return ToolResult(success=False, error="查询刷流任务返回格式异常")
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks") or tasks.get("data") or []
    if not isinstance(tasks, list):
        tasks = []
    items = [
        {
            "id": t.get("id") if isinstance(t, dict) else None,
            "name": t.get("name") if isinstance(t, dict) else None,
            "site": t.get("site") if isinstance(t, dict) else None,
            "state": t.get("state") if isinstance(t, dict) else None,
            "free": t.get("free") if isinstance(t, dict) else None,
        }
        for t in tasks
        if isinstance(t, dict)
    ]
    return ToolResult(success=True, data={"total": len(items), "items": items})
