"""媒体服务器配置工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class MediaserverListTool(BaseTool):
    name = "mediaserver_list"
    description = (
        "列出已配置的媒体服务器（Emby/Jellyfin/Plex 等），API Key/Token 已脱敏。当用户问'媒体服务器配置'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class MediaserverConfigSaveTool(BaseTool):
    name = "mediaserver_config_save"
    description = (
        "更新已有媒体服务器的连接配置（合并传入字段，如 host/port/apikey，供 Emby/Jellyfin/Plex）。"
        "需确认。当用户说'媒体服务器地址/密钥改了帮我更新'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "媒体服务器名称（来自 mediaserver_list）"},
            "config": {
                "type": "object",
                "description": "要修改的配置字段，如 host/port/apikey",
            },
        },
        "required": ["name", "config"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
