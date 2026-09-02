"""媒体库目录 / 目录同步工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class MediaLibraryDirsGetTool(BaseTool):
    name = "media_library_dirs_get"
    description = "读取媒体库目录配置（电影/剧集/动漫/未识别各自的目录与存储后端）。当用户问媒体库目录时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "library:view"


class MediaLibraryDirAddTool(BaseTool):
    name = "media_library_dir_add"
    description = "在媒体库某分类（movie/tv/anime/unknown）下新增目录，可指定存储后端。需确认。"
    parameters = {
        "type": "object",
        "properties": {
            "path_type": {"type": "string", "enum": ["movie", "tv", "anime", "unknown"], "description": "分类"},
            "path": {"type": "string", "description": "要添加的目录路径"},
            "backend": {"type": "string", "description": "存储后端名；留空为本地 local"},
        },
        "required": ["path_type", "path"],
    }
    level = ToolLevel.WRITE
    permission = "library:manage"


class MediaLibraryDirRemoveTool(BaseTool):
    name = "media_library_dir_remove"
    description = "移除媒体库某分类下的一个目录。需确认。"
    parameters = {
        "type": "object",
        "properties": {
            "path_type": {"type": "string", "enum": ["movie", "tv", "anime", "unknown"]},
            "path": {"type": "string", "description": "要移除的目录路径"},
        },
        "required": ["path_type", "path"],
    }
    level = ToolLevel.WRITE
    permission = "library:manage"


class StorageBackendListTool(BaseTool):
    name = "storage_backend_list"
    description = "列出存储后端（本地/WebDAV/SMB 等），供配置同步任务选择来源/目的后端时参考。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "storage:view"


class SyncPathListTool(BaseTool):
    name = "sync_path_list"
    description = "列出目录同步任务（源→目的、同步方式、启停状态）。当用户问'目录同步/同步任务'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "storage:view"


class SyncPathSaveTool(BaseTool):
    name = "sync_path_save"
    description = (
        "新增或更新目录同步任务。mode 取值 copy(复制)/link(硬链接)/softlink(软链接)/move(移动)；"
        "src_backend/dst_backend 为 local 或 storage_backend_list 返回的后端名；dest 留空表示同库整理。需确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "源目录（必填）"},
            "dest": {"type": "string", "description": "目的目录；留空为同库整理"},
            "mode": {
                "type": "string",
                "enum": ["copy", "link", "softlink", "move"],
                "description": "同步方式",
                "default": "copy",
            },
            "src_backend": {"type": "string", "description": "源存储后端(默认 local)"},
            "dst_backend": {"type": "string", "description": "目的存储后端(默认 local)"},
            "unknown": {"type": "string", "description": "可选：未知目录的归属路径"},
            "enabled": {"type": "boolean", "description": "是否启用", "default": True},
            "sid": {"type": "integer", "description": "更新已有任务时的 id；新增填 0"},
        },
        "required": ["source"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
