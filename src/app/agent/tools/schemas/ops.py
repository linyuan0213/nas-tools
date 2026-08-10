"""媒体库 / 整理 / 调度 / 系统 / 记忆工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class LibraryCheckTool(BaseTool):
    name = "library_check"
    description = "检查某部影视作品是否已入库、缺哪几集。当用户问'库里有没有X/X剧缺哪集'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "影视标题（可含年份）"},
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "可选，媒体类型"},
        },
        "required": ["title"],
    }
    level = ToolLevel.READ


class TransferRunTool(BaseTool):
    name = "transfer_run"
    description = "手动运行媒体文件转移整理（下载目录 → 媒体库）。当用户要求'整理/转移文件'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "source_path": {"type": "string", "description": "源目录"},
            "target_path": {"type": "string", "description": "可选，目标目录（留空用默认媒体库目录）"},
            "operation": {
                "type": "string",
                "enum": ["copy", "link", "move"],
                "description": "默认 link",
                "default": "link",
            },
        },
        "required": ["source_path"],
    }
    level = ToolLevel.WRITE


class SchedulerListTool(BaseTool):
    name = "scheduler_list"
    description = "列出所有定时任务及运行状态。当用户问'有哪些定时任务/某任务是否在跑'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class SchedulerRunTool(BaseTool):
    name = "scheduler_run"
    description = "立即运行一次指定定时任务（如 sync_rss、subscribe_search、transfer、cookiecloud）。"
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "任务 ID（可先 scheduler_list 查询）"},
        },
        "required": ["job_id"],
    }
    level = ToolLevel.WRITE


class SystemStatusTool(BaseTool):
    name = "system_status"
    description = "查询系统状态（CPU、内存、磁盘、运行时间）。当用户问'系统负载/磁盘占用'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class MemoryClearTool(BaseTool):
    name = "memory_clear"
    description = "清空当前会话的对话记忆。当用户说'清空对话/忘记刚才的聊天'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.WRITE
