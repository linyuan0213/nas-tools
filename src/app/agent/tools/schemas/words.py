"""识别词管理工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class WordsListTool(BaseTool):
    name = "words_list"
    description = (
        "查询自定义识别词配置（分组：作品标题/年份、屏蔽词、替换词、集偏移等）。"
        "当用户问'识别词/为什么某部片识别不对/有哪些自定义识别规则'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class WordsAddTool(BaseTool):
    name = "words_add"
    description = (
        "新增/更新自定义识别词（屏蔽词/替换词/集偏移）。影响全局识别，需确认。"
        "当用户说'把某词屏蔽掉/替换成/加集偏移'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "group_id": {
                "type": "integer",
                "description": "识别词组 ID（通用组为 -1，可先 words_list 查询；0 表示新建作品组）",
            },
            "word_type": {
                "type": "integer",
                "description": "类型：1=屏蔽，2=替换，3=集偏移",
            },
            "replaced": {"type": "string", "description": "被替换/屏蔽的词"},
            "replace": {"type": "string", "description": "替换为（屏蔽时留空）"},
            "offset": {"type": "string", "description": "集偏移量，如 +1/-1（仅集偏移类型）"},
            "season": {"type": "integer", "description": "季号（可选，默认 -2 全部）"},
            "enabled": {"type": "boolean", "description": "是否启用，默认 true"},
            "tmdb_id": {"type": "integer", "description": "group_id 为 0 新建作品组时必填的 TMDB ID"},
            "tmdb_type": {"type": "string", "description": "新建组时的类型：movie/tv/anime"},
        },
        "required": ["word_type", "replaced"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"


class WordsToggleTool(BaseTool):
    name = "words_toggle"
    description = "启用/禁用自定义识别词。影响全局识别，需确认。当用户说'把某条识别词停用/启用'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "word_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "识别词 ID 列表（words_list 查询）",
            },
            "enabled": {"type": "boolean", "description": "true 启用，false 禁用"},
        },
        "required": ["word_ids", "enabled"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"


class WordsDeleteTool(BaseTool):
    name = "words_delete"
    description = "删除识别词或整个识别词组。影响全局识别，需确认。当用户说'删除某条识别词/删除某作品识别组'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "word_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "要删除的识别词 ID 列表",
            },
            "group_id": {"type": "integer", "description": "删除整个识别词组时传组 ID"},
        },
    }
    level = ToolLevel.DANGEROUS
    permission = "setting:update"
