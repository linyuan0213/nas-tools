"""系统日志查询工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class SystemLogsTool(BaseTool):
    name = "system_logs"
    description = (
        "查询系统运行日志（最近内存缓冲）。当用户问'为什么X失败/报错/出问题/刚才发生了什么/"
        "某模块日志'时调用，用于诊断下载失败、转移报错、站点异常等。错误/警告日志优先返回。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "可选，按日志来源模块过滤（如 transfer / search / indexer / scheduler）",
            },
            "level": {
                "type": "string",
                "enum": ["DEBUG", "INFO", "WARNING", "ERROR"],
                "description": "可选，按级别过滤；不指定时错误/警告优先",
            },
            "keyword": {
                "type": "string",
                "description": "可选，按关键字过滤日志内容",
            },
            "limit": {
                "type": "integer",
                "description": "可选，返回条数上限（默认 50，最大 200）",
                "default": 50,
            },
        },
        "required": [],
    }
    level = ToolLevel.READ
    permission = "log:view"
