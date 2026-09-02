"""媒体服务器（Emby/Jellyfin/Plex）配置工具 handler"""

from app.agent.tools.base import ToolResult
from app.agent.tools.context import ToolContext

# 默认媒体服务器类型显示名映射（用于提示）
_TYPE_NAMES = {
    "emby": "Emby",
    "jellyfin": "Jellyfin",
    "plex": "Plex",
}

_MASK_KEYS = ("apikey", "api_key", "token", "password", "secret")


def mediaserver_list(ctx: ToolContext) -> ToolResult:
    """列出已配置的媒体服务器（连接参数保留，密钥类脱敏）"""
    svc = ctx.media_server_config_service
    if not svc:
        return ToolResult(success=False, error="媒体服务器服务不可用")
    try:
        info = svc.get_media_servers_info()
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询媒体服务器失败: {e}")
    items = []
    for name, server in (info.get("servers") or {}).items():
        items.append(
            {
                "id": server.get("id"),
                "name": name,
                "enabled": server.get("enabled"),
                "is_default": server.get("is_default"),
                "config": {k: ("***" if v and _is_secret(k) else v) for k, v in (server.get("config") or {}).items()},
            }
        )
    return ToolResult(success=True, data={"default_server": info.get("default_server"), "items": items})


def mediaserver_config_save(ctx: ToolContext, name: str, config: dict, confirmed: bool = False) -> ToolResult:
    """更新已有媒体服务器的连接配置（合并传入字段；支持 enabled/is_default 置顶），需确认。"""
    svc = ctx.media_server_config_service
    if not svc:
        return ToolResult(success=False, error="媒体服务器服务不可用")
    if not name or not isinstance(config, dict) or not config:
        return ToolResult(success=False, error="name 与 config 必填")
    try:
        info = svc.get_media_servers_info()
        current = (info.get("servers") or {}).get(name) or {}
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"查询媒体服务器失败: {e}")
    if not current:
        configured = list((info or {}).get("servers") or {})
        return ToolResult(success=False, error=f"媒体服务器不存在: {name}（已配置: {configured}）")

    if not confirmed:
        return ToolResult(
            success=True,
            need_confirm=True,
            data={
                "action": "mediaserver_save",
                "name": name,
                "message": f"更新媒体服务器「{name}」配置需确认，字段: {list(config.keys())}",
            },
        )

    merged = dict(current.get("config") or {})
    for k in ("enabled", "is_default"):
        if config.get(k) is not None:
            merged[k] = 1 if config[k] else 0
    merged.update({k: v for k, v in config.items() if v is not None})
    data = {"type": name, **merged}
    try:
        result = svc.save_config(data)
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=f"保存媒体服务器失败: {e}")
    if not getattr(result, "success", True):
        return ToolResult(success=False, error=getattr(result, "msg", "保存失败"))
    return ToolResult(success=True, data={"name": name, "message": f"媒体服务器「{name}」配置已保存"})


def _is_secret(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in _MASK_KEYS)


HANDLERS = {
    "mediaserver_list": mediaserver_list,
    "mediaserver_config_save": mediaserver_config_save,
}
