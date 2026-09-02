"""下载器配置工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class DownloaderConfigGetTool(BaseTool):
    name = "downloader_config_get"
    description = (
        "列出下载器及连接配置（host/port/用户名可见，密码已脱敏）。当用户问'下载器怎么配置/在哪台机器'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "did": {"type": "integer", "description": "下载器 id；不填返回全部"},
        },
    }
    level = ToolLevel.READ
    permission = "download:view"


class DownloaderConfigSaveTool(BaseTool):
    name = "downloader_config_save"
    description = (
        "保存下载器：did>0 更新已有下载器连接（合并传入字段，支持 host/port/username/password/enabled）；"
        "did=0 新增下载器（需 name 与 ctype，id 自动生成）。需确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "did": {
                "type": "integer",
                "description": "下载器 id（downloader_config_get 可得）；新增填 0",
                "default": 0,
            },
            "config": {
                "type": "object",
                "description": "连接配置字段，如 host/port/username/password",
            },
            "name": {"type": "string", "description": "新增时的名称（更新时可选重命名）"},
            "ctype": {"type": "string", "description": "新增时的类型：qbittorrent / transmission 等"},
            "enabled": {"type": "boolean", "description": "可选，切换启用状态"},
        },
        "required": ["config"],
    }
    level = ToolLevel.WRITE
    permission = "download:manage"
