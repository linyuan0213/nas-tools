"""刷流工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class BrushStatusTool(BaseTool):
    name = "brush_status"
    description = (
        "查询刷流任务状态（任务列表：名称、状态、站点、统计数据等）。"
        "当用户问'刷流任务/刷流跑得怎么样/XX刷流任务'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "brush:view"
