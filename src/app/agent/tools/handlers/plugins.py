"""插件工具 handler"""

import log
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def plugin_list(ctx: ToolContext, enabled_only: bool = False) -> ToolResult:
    """列出已安装插件（复用 PluginFrameworkService.list_plugins，与 UI 一致）"""
    try:
        plugins = ctx.plugin_framework_service.list_plugins()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"列出插件失败: {e}")
    if enabled_only:
        plugins = [p for p in plugins if p.get("enabled")]
    items = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "version": p.get("version"),
            "category": p.get("category"),
            "description": p.get("description"),
            "enabled": p.get("enabled"),
            "builtin": p.get("is_builtin"),
            "supports_run": p.get("supports_run"),
        }
        for p in plugins
    ]
    return ToolResult(success=True, data={"total": len(items), "items": items})


def plugin_info(ctx: ToolContext, plugin_id: str) -> ToolResult:
    """查看单个插件详情（清单 + 启用状态 + 配置）"""
    try:
        plugins = ctx.plugin_framework_service.list_plugins()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询插件失败: {e}")
    plugin = next((p for p in plugins if p.get("id") == plugin_id), None)
    if not plugin:
        return ToolResult(success=False, error=f"插件不存在: {plugin_id}")
    config = {}
    try:
        config = ctx.plugin_framework_service.get_config(plugin_id) or {}
    except Exception:  # noqa: BLE001
        log.warn(f"[AgentTool]读取插件 {plugin_id} 配置失败，忽略")
    return ToolResult(success=True, data={**plugin, "config": config})


def plugin_run(ctx: ToolContext, plugin_id: str, confirmed: bool = False) -> ToolResult:
    """立即运行插件（调用插件 run 方法）。运行有副作用，需用户确认。"""
    try:
        manifest = ctx.plugin_framework_service.get_manifest(plugin_id)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询插件失败: {e}")
    if not manifest:
        return ToolResult(success=False, error=f"插件不存在: {plugin_id}")
    if not getattr(getattr(manifest, "backend", None), "supports_run", False):
        return ToolResult(success=False, error=f"插件 {plugin_id} 不支持运行")
    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "run", "plugin_id": plugin_id, "message": f"运行插件「{manifest.name}」需确认"},
        )
    try:
        ctx.plugin_framework_service.run_plugin(plugin_id)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"运行插件失败: {e}")
    return ToolResult(success=True, data={"plugin_id": plugin_id, "message": "运行任务已启动"})


HANDLERS = {
    "plugin_list": plugin_list,
    "plugin_info": plugin_info,
    "plugin_run": plugin_run,
}
