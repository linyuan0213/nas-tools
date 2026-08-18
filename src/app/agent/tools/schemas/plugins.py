"""插件工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class PluginListTool(BaseTool):
    name = "plugin_list"
    description = "列出已安装插件（名称、版本、状态、分类、描述）。当用户问'有哪些插件/插件列表'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "enabled_only": {"type": "boolean", "description": "是否仅列出已启用插件", "default": False},
        },
    }
    level = ToolLevel.READ
    permission = "plugin:view"


class PluginInfoTool(BaseTool):
    name = "plugin_info"
    description = "查看单个插件的详情（清单、启用状态、配置）。当用户问'某个插件怎么样/配置'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "plugin_id": {"type": "string", "description": "插件 ID"},
        },
        "required": ["plugin_id"],
    }
    level = ToolLevel.READ
    permission = "plugin:view"


class PluginRunTool(BaseTool):
    name = "plugin_run"
    description = (
        "立即运行插件（调用插件 run 方法）。运行插件有副作用，属于需要确认的操作。当用户说'运行/执行某个插件'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "plugin_id": {"type": "string", "description": "插件 ID"},
        },
        "required": ["plugin_id"],
    }
    level = ToolLevel.WRITE
    permission = "plugin:manage"
