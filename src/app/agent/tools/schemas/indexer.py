"""索引器配置工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class IndexerConfigGetTool(BaseTool):
    name = "indexer_config_get"
    description = (
        "列出索引器客户端（builtin/jackett/prowlarr 等）的启用与配置状态，密钥已脱敏。"
        "当用户问'搜索用了哪些索引器/配置'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class IndexerConfigSaveTool(BaseTool):
    name = "indexer_config_save"
    description = (
        "设置索引器客户端的启用状态并更新连接配置（如 jackett/prowlarr 的 host/apikey），需确认。"
        "当用户说'启用/停用某个索引器/改了索引器地址'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "索引器客户端 id，如 builtin/jackett/prowlarr/mteam"},
            "enabled": {"type": "boolean", "description": "是否启用"},
            "config": {
                "type": "object",
                "description": "要修改的连接配置字段，如 host/api_key",
            },
        },
        "required": ["client_id", "enabled"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
