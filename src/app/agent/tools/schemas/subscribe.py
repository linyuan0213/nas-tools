"""订阅管理工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class SubscribeAddTool(BaseTool):
    name = "subscribe_add"
    description = "添加 RSS 订阅追新（电影或电视剧）。当用户说'订阅/追更某部作品'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "影视标题"},
            "media_type": {
                "type": "string",
                "enum": ["movie", "tv"],
                "description": "媒体类型，默认 movie",
                "default": "movie",
            },
            "year": {"type": "integer", "description": "可选，年份"},
            "season": {"type": "integer", "description": "可选，电视剧季号"},
        },
        "required": ["title"],
    }
    level = ToolLevel.WRITE
    permission = "subscription:manage"


class SubscribeListTool(BaseTool):
    name = "subscribe_list"
    description = "查询当前订阅列表（含缺失集信息）。当用户问'我订阅了什么/某剧追到哪儿了'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "可选，限定类型"},
        },
    }
    level = ToolLevel.READ


class SubscribeDetailTool(BaseTool):
    name = "subscribe_detail"
    description = (
        "查询单个订阅的详细信息（进度、缺集、站点、过滤条件等）。当用户问'某部剧订阅到哪了/缺哪几集/某订阅详情'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "剧名（模糊匹配）"},
            "tmdb_id": {"type": "integer", "description": "可选，TMDB ID"},
        },
        "required": ["title"],
    }
    level = ToolLevel.READ
    permission = "subscription:view"


class SubscribeDeleteTool(BaseTool):
    name = "subscribe_delete"
    description = "删除订阅。当用户要求取消某部作品的订阅时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "sub_id": {"type": "integer", "description": "订阅 ID（可先 subscribe_list 查询）"},
            "media_type": {
                "type": "string",
                "enum": ["movie", "tv"],
                "description": "媒体类型，默认 movie",
                "default": "movie",
            },
        },
        "required": ["sub_id"],
    }
    level = ToolLevel.DANGEROUS
    permission = "subscription:manage"
