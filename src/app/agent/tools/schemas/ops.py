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
    permission = "library:manage"


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
    permission = "service:manage"


class SystemStatusTool(BaseTool):
    name = "system_status"
    description = "查询系统状态（版本、运行时长、内存使用等）。当用户问'系统状态/运行了多久'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class SiteUpdateCookieTool(BaseTool):
    name = "site_update_cookie"
    description = (
        "更新站点 Cookie（需用户确认，用于维护站点登录态）。当用户提供站点 Cookie 并要求更新时调用，必须先确认再执行。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "site_id": {"type": "integer", "description": "站点 ID（可先 site_status 查询）"},
            "cookie": {"type": "string", "description": "新的 Cookie 值"},
        },
        "required": ["site_id", "cookie"],
    }
    level = ToolLevel.DANGEROUS
    permission = "site:manage"


class StatsSummaryTool(BaseTool):
    name = "stats_summary"
    description = (
        "查询系统数据总览（媒体库规模、下载记录统计、站点数量、系统运行信息等）。"
        "当用户问'现在什么情况/总览/最近下载了多少/有多少站点'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class TransferHistoryTool(BaseTool):
    name = "transfer_history"
    description = (
        "查询媒体转移/入库历史（标题、季集、目标文件名、时间）。"
        "当用户问'哪部片什么时候入库的/转移历史/入库记录'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "可选，按标题关键字过滤"},
            "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            "page_num": {"type": "integer", "description": "每页条数，默认 20", "default": 20},
        },
    }
    level = ToolLevel.READ


class KbStatusTool(BaseTool):
    name = "kb_status"
    description = "查询知识库状态（各命名空间索引块数）。当用户问'知识库有多少内容/索引情况'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class IndexerStatusTool(BaseTool):
    name = "indexer_status"
    description = (
        "查询索引器统计（各索引器搜索次数、成功/失败、平均耗时）。"
        "当用户问'索引器/搜索服务正常吗/哪个索引器有问题'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "search:view"


class TorrentRemoverStatusTool(BaseTool):
    name = "torrent_remover_status"
    description = "查询自动删种任务列表（名称、站点、规则、状态）。当用户问'自动删种任务/删种规则'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class StorageStatusTool(BaseTool):
    name = "storage_status"
    description = "查询存储后端列表（名称、类型、启用状态）。当用户问'存储后端/存储空间/磁盘'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ


class MemoryForgetTool(BaseTool):
    name = "memory_forget"
    description = "删除长程语义记忆中的一条用户偏好。当用户说'忘掉/删除我的某个偏好'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要删除的偏好内容，如 '偏好 4K REMUX'"},
        },
        "required": ["text"],
    }
    level = ToolLevel.WRITE
    permission = "agent:manage"


class MemoryClearTool(BaseTool):
    name = "memory_clear"
    description = "清空当前会话的对话记忆。当用户说'清空对话/忘记刚才的聊天'时调用。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.WRITE
    permission = "agent:manage"
