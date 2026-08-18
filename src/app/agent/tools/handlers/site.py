"""站点工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def site_status(ctx: ToolContext) -> ToolResult:
    """查询站点状态（启用列表 + 认证配置 + 统计开关）"""
    try:
        sites = ctx.site_service.get_sites()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询站点状态失败: {e}")
    if not isinstance(sites, list):
        return ToolResult(success=False, error="查询站点状态返回格式异常")
    items = []
    enabled = 0
    for s in sites:
        if not isinstance(s, dict):
            continue
        if s.get("enabled"):
            enabled += 1
        items.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "enabled": bool(s.get("enabled")),
                "rss_enable": bool(s.get("rss_enable")),
                "statistic_enable": bool(s.get("statistic_enable")),
                "brush_enable": bool(s.get("brush_enable")),
                "has_auth": bool(s.get("cookie") or s.get("api_key") or s.get("bearer_token")),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "enabled": enabled, "items": items})


def site_update_cookie(ctx: ToolContext, site_id: int, cookie: str, confirmed: bool = False) -> ToolResult:
    """更新站点 Cookie（有副作用，需用户确认）"""
    if not cookie or not str(cookie).strip():
        return ToolResult(success=False, error="Cookie 不能为空")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "update_cookie", "site_id": site_id, "message": f"更新站点 {site_id} 的 Cookie 需确认"},
        )
    try:
        ctx.site_service.update_site_cookie_ua(siteid=site_id, cookie=str(cookie).strip(), ua="")
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"更新站点 Cookie 失败: {e}")
    return ToolResult(success=True, data={"site_id": site_id, "message": "站点 Cookie 已更新"})


HANDLERS = {
    "site_status": site_status,
    "site_update_cookie": site_update_cookie,
}
