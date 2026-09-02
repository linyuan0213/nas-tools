"""全量配置清单应用工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class ConfigApplyManifestTool(BaseTool):
    name = "config_apply_manifest"
    description = (
        "批量应用一份全量配置清单。清单结构："
        "{downloaders:[{id,name?,host?,port?,username?,password?,enabled?}], "
        "message_clients:[{name,type,enabled,config}], "
        "plugins:[{plugin_id,action: enable|disable|config,config?}], "
        "mediaservers:[{name,enabled,config}], "
        "indexers:[{client_id,enabled,config}], "
        "scraper:{...}, config:{'点路径':值}}。"
        "先整体校验预览，用户确认后统一应用并逐项报告。当用户贴出一份配置清单要求'全部配好'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest": {
                "type": "object",
                "description": "从用户提供的 Markdown 配置清单中解析出的结构化配置对象",
            },
        },
        "required": ["manifest"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
