"""用户 RSS 任务工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def rss_task_list(ctx: ToolContext) -> ToolResult:
    """查询用户自定义 RSS 任务列表"""
    try:
        tasks = ctx.user_rss_service.get_tasks()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询 RSS 任务失败: {e}")
    if not isinstance(tasks, list):
        tasks = []
    items = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        items.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "address": (t.get("address") or []) if isinstance(t.get("address"), list) else [],
                "interval": t.get("interval"),
                "state": t.get("state"),
                "note": t.get("note"),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})
