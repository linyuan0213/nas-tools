"""下载器配置工具 handler — 读取（脱敏）与连接配置更新"""

from app.agent.sanitize import mask_config_values
from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext


def downloader_config_get(ctx: ToolContext, did: int | None = None) -> ToolResult:
    """列出下载器及连接配置（密码已脱敏），did 指定时仅返回单个"""
    core = ctx.downloader_core
    if not core:
        return ToolResult(success=False, error="下载器服务不可用")
    try:
        data = core.get_downloader_conf(did=did) or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询下载器失败: {e}")
    items = []
    records = {str(did): data} if did else (data or {})
    for cid, item in records.items():
        cfg = item.get("config") or {}
        items.append(
            {
                "id": cid,
                "name": item.get("name"),
                "type": item.get("type"),
                "enabled": item.get("enabled"),
                "transfer": item.get("transfer"),
                "is_default": item.get("is_default"),
                "config": mask_config_values(cfg),
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def downloader_config_save(
    ctx: ToolContext,
    config: dict,
    did: int = 0,
    name: str = "",
    ctype: str = "",
    enabled: bool | None = None,
    confirmed: bool = False,
) -> ToolResult:
    """更新已有下载器（did>0，合并连接字段）或新增下载器（did=0，需 name 与 ctype）。"""
    core = ctx.downloader_core
    if not core:
        return ToolResult(success=False, error="下载器服务不可用")
    if not isinstance(config, dict) or not config:
        return ToolResult(success=False, error="config 必须是非空对象")

    did = int(did or 0)
    if did:
        try:
            current = core.get_downloader_conf(did=did)
        except Exception as e:  # noqa: BLE001
            return ToolResult(success=False, error=f"查询下载器失败: {e}")
        if not current:
            return ToolResult(success=False, error=f"下载器不存在: {did}")
    else:
        if not name or not ctype:
            return ToolResult(success=False, error="新增下载器需提供 name 与 ctype（类型如 qbittorrent/transmission）")
        current = {}

    if not confirmed:
        action = "新增下载器" if not did else f"更新下载器「{current.get('name') or name}」"
        return ToolResult(
            success=True,
            need_confirm=True,
            data={"action": "downloader_save", "did": did, "message": f"{action}需确认，字段: {list(config.keys())}"},
        )

    try:
        target_name, _, _ = core.upsert_downloader(
            did=did or None, name=name, dtype=ctype, config_overlay=config, enabled=enabled
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存下载器失败: {e}")
    return ToolResult(success=True, data={"did": did, "message": f"下载器「{target_name}」已保存"})
