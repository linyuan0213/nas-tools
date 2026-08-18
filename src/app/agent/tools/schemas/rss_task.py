"""用户 RSS 任务工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class RssTaskListTool(BaseTool):
    name = "rss_task_list"
    description = (
        "查询用户自定义 RSS 任务列表（名称、订阅源地址、更新时间、状态等）。"
        "当用户问'我的 RSS 任务/自定义订阅任务'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
