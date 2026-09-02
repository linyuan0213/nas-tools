"""系统配置工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class ConfigGetTool(BaseTool):
    name = "config_get"
    description = (
        "读取系统配置节点（app/media/pt/subscribe/laboratory/agent），敏感字段已脱敏为 ***。"
        "当用户问'当前XX配置是什么/查看设置'时调用，用于诊断与辅助修改。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": "配置节点，可取值 app/media/pt/subscribe/laboratory/agent；留空返回节点概览",
            },
        },
        "required": [],
    }
    level = ToolLevel.READ
    permission = "setting:view"


class ConfigSetTool(BaseTool):
    name = "config_set"
    description = (
        "按扁平点路径写回系统配置（仅限 app/media/pt/subscribe/laboratory/agent 节点的非敏感字段，"
        '如 {"media.tmdb_language": "zh"}）。写操作需确认。当用户说\'帮我改/设置某个系统配置\'时调用。'
    )
    parameters = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "description": "扁平键→值映射（点号路径，如 media.movie_path），值必须与当前类型一致",
            },
        },
        "required": ["config"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
