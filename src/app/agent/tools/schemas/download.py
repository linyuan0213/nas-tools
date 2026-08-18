"""下载管理工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class DownloadAddLinkTool(BaseTool):
    name = "download_add_link"
    description = "通过磁力链接 / 种子 URL 直接添加下载任务。当用户给出具体链接要求下载时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "link": {"type": "string", "description": "磁力链接（magnet:）或种子下载地址"},
            "title": {"type": "string", "description": "可选，资源标题（留空则用链接推断）"},
            "save_path": {"type": "string", "description": "可选，保存路径"},
        },
        "required": ["link"],
    }
    level = ToolLevel.WRITE
    permission = "download:manage"


class MediaDownloadTool(BaseTool):
    name = "media_download"
    description = "按标题搜索并自动择优下载影视资源。当用户说'下载/想看某部作品'且未给出具体链接时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "影视标题（可含年份/季集）"},
            "media_format": {"type": "string", "description": "可选，如 4K/1080p"},
        },
        "required": ["title"],
    }
    level = ToolLevel.WRITE
    permission = "download:manage"


class DownloadListTool(BaseTool):
    name = "download_list"
    description = "查询正在下载的任务列表（标题、进度、速度、状态）。当用户问'下载到哪了/下载进度'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "page_size": {"type": "integer", "description": "返回条数，默认 10", "default": 10},
        },
    }
    level = ToolLevel.READ


class DownloadControlTool(BaseTool):
    name = "download_control"
    description = "控制下载任务：开始 / 停止 / 重新校验 / 删除。删除为危险操作需用户确认。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "recheck", "remove"], "description": "操作类型"},
            "ids": {"type": "array", "items": {"type": "string"}, "description": "任务 hash 列表"},
            "delete_file": {"type": "boolean", "description": "仅 remove 时有效，是否同时删除文件", "default": False},
        },
        "required": ["action", "ids"],
    }
    level = ToolLevel.WRITE
    permission = "download:manage"


class DownloaderStatusTool(BaseTool):
    name = "downloader_status"
    description = "查询下载器状态（在线情况、速度、剩余空间）。当用户问'下载器正常吗/磁盘还剩多少'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class DownloadHistoryListTool(BaseTool):
    name = "download_history_list"
    description = (
        "查询下载历史（已完成/曾下载过的记录：标题、季集、状态、时间）。"
        "当用户问'下载过什么/历史记录/某部片下过没有'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            "page_size": {"type": "integer", "description": "返回条数，默认 10", "default": 10},
            "keyword": {"type": "string", "description": "可选，按标题关键字过滤"},
        },
    }
    level = ToolLevel.READ
