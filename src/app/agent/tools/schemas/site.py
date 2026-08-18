"""站点工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class SiteStatusTool(BaseTool):
    name = "site_status"
    description = (
        "查询站点状态（已启用站点列表、名称、是否启用、统计信息等）。当用户问'哪些站点/站点状态/XX站在线吗'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "site:view"
