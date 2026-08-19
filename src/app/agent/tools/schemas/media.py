"""媒体检索与知识库工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class MediaSearchTool(BaseTool):
    name = "media_search"
    description = (
        "搜索影视资源（种子）。传入自然语言查询（可含类型、年份、季、集），"
        "系统统一进行意图识别、TMDB 匹配与站点并发搜索，返回按合集/质量/做种排序的结果。"
        "当用户想'找/搜/有没有'某部影视资源时调用，不要用 web_search 搜索影视资源。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言搜索词，如'流浪地球 2019'、'权力的游戏 第2季'"},
            "site": {"type": "array", "items": {"type": "string"}, "description": "可选，限定站点名列表"},
            "seeders": {"type": "integer", "description": "可选，最低做种数"},
        },
        "required": ["query"],
    }
    level = ToolLevel.READ


class MediaDetailTool(BaseTool):
    name = "media_detail"
    description = "查询影视作品的详细信息（标题/年份/类型/简介/评分）。当用户询问某部作品的基本信息时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "tmdb_id": {"type": "integer", "description": "TMDB ID"},
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "媒体类型"},
        },
        "required": ["tmdb_id", "media_type"],
    }
    level = ToolLevel.READ


class KbSearchTool(BaseTool):
    name = "kb_search"
    description = (
        "检索系统知识库（使用文档、FAQ、配置指南、消息模板说明）。"
        "当用户询问'怎么配置/怎么用/什么意思/报错原因'等知识类问题时调用，返回带来源的引用片段。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "问题或关键词"},
            "namespace": {
                "type": "string",
                "enum": ["media_library", "messages", "faq", "operations"],
                "description": "可选，限定知识域",
            },
        },
        "required": ["query"],
    }
    level = ToolLevel.READ
