"""网页搜索工具 Schema — 基于内置 Chrome 服务（nexus-chrome）"""

from app.agent.tools.base import BaseTool, ToolLevel


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "使用内置无头浏览器在 Google/Bing/Baidu 搜索网页，返回结果标题、链接与摘要。"
        "用于查询互联网上的信息：新闻、攻略、资料、实时动态、网页内容等。"
        "注意：若用户在'找/搜某部影视剧集的资源/种子/有没有得下'，应调用 media_search 而非本工具；"
        "若需浏览某个具体网址页面，应调用 browser_fetch。"
        "引擎可选 google/bing/baidu（默认 google）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "engine": {
                "type": "string",
                "description": "搜索引擎：google / bing / baidu",
                "enum": ["google", "bing", "baidu"],
                "default": "google",
            },
            "limit": {"type": "integer", "description": "返回结果条数（1-10）", "default": 5},
        },
        "required": ["query"],
    }
    level = ToolLevel.READ
