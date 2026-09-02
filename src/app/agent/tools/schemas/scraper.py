"""刮削配置工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class ScraperConfigGetTool(BaseTool):
    name = "scraper_config_get"
    description = "读取刮削配置（NFO/图片等各节），密钥类字段已脱敏。当用户问'刮削/元数据配置'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class ScraperConfigSaveTool(BaseTool):
    name = "scraper_config_save"
    description = (
        "整体保存刮削配置（覆盖 scraper_nfo / scraper_pic 等节）。复杂嵌套，需先 scraper_config_get 参考结构，"
        "仅建议修改小字段。需确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "description": "完整刮削配置对象（含 scraper_nfo/scraper_pic 等节）",
            },
        },
        "required": ["config"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
