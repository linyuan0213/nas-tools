"""索引器配置工具 handler — 读取（脱敏）与开关/连接配置更新"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext

_MASK_KEYS = ("apikey", "api_key", "token", "password", "secret", "passkey")


def indexer_config_get(ctx: ToolContext) -> ToolResult:
    """列出索引器客户端及其启用/配置状态（密钥脱敏）"""
    svc = ctx.indexer_config_service
    if not svc:
        return ToolResult(success=False, error="索引器服务不可用")
    try:
        configs = svc.get_all_configs() or []
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询索引器失败: {e}")
    items = []
    for c in configs:
        cfg = c.get("config") or {}
        items.append(
            {
                "client_id": c.get("client_id"),
                "enabled": c.get("enabled"),
                "configured": bool(cfg.get("host") or cfg.get("api_key") or c.get("client_id") == "builtin"),
                "config": {k: ("***" if v and _is_secret(k) else v) for k, v in cfg.items()},
            }
        )
    return ToolResult(success=True, data={"total": len(items), "items": items})


def indexer_config_save(
    ctx: ToolContext, client_id: str, enabled: bool, config: dict, confirmed: bool = False
) -> ToolResult:
    """设置索引器客户端的启用状态与连接配置（合并传入字段），需确认。"""
    svc = ctx.indexer_config_service
    if not svc:
        return ToolResult(success=False, error="索引器服务不可用")
    if not client_id:
        return ToolResult(success=False, error="client_id 必填")
    if not isinstance(config, dict):
        return ToolResult(success=False, error="config 必须是非空对象")

    if not confirmed:
        action = "启用" if enabled else "禁用"
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "indexer_save",
                "client_id": client_id,
                "message": f"{action}索引器「{client_id}」需确认"
                + (f"，配置字段: {list(config.keys())}" if config else ""),
            },
        )

    # 合并已有配置，保留未改字段
    existing = {}
    try:
        cur = svc.get_config(client_id)
        if cur:
            existing = cur.get("config") or {}
    except Exception:  # noqa: BLE001
        existing = {}
    merged = dict(existing)
    merged.update({k: v for k, v in config.items() if v is not None})

    data = {"type": client_id, "enabled": 1 if enabled else 0}
    for k, v in merged.items():
        data[f"{client_id}.{k}"] = v
    try:
        result = svc.save_config(data)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存索引器失败: {e}")
    if not getattr(result, "success", True):
        return ToolResult(success=False, error=getattr(result, "msg", "保存失败"))
    return ToolResult(success=True, data={"client_id": client_id, "message": f"索引器「{client_id}」配置已保存"})


def _is_secret(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in _MASK_KEYS)


HANDLERS = {
    "indexer_config_get": indexer_config_get,
    "indexer_config_save": indexer_config_save,
}
