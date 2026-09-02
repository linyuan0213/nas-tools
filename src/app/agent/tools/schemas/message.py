"""消息通知渠道工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class MessageClientListTool(BaseTool):
    name = "message_client_list"
    description = (
        "列出已配置的消息通知渠道（名称/类型/启用状态），配置中的 Token/密钥已脱敏。"
        "当用户问'消息通知有哪些渠道/通知配置'时调用。"
    )
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class MessageChannelTypesTool(BaseTool):
    name = "message_channel_types"
    description = "列出支持的消息通知渠道类型及各类型需要填写的配置字段，供新增/修改渠道前参考。"
    parameters = {"type": "object", "properties": {}}
    level = ToolLevel.READ
    permission = "setting:view"


class MessageClientSaveTool(BaseTool):
    name = "message_client_save"
    description = (
        "新增或更新消息通知渠道（先调用 message_channel_types 确认类型所需字段）。"
        "配置会写入真实 Token/密钥，属敏感操作需确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "渠道名称，如 我的Telegram"},
            "ctype": {"type": "string", "description": "渠道类型，如 telegram/serverchan/webhook/bark 等"},
            "config": {"type": "object", "description": "渠道配置对象（字段参考 message_channel_types）"},
            "enabled": {"type": "boolean", "description": "是否启用，默认 true"},
            "cid": {"type": "integer", "description": "更新已有渠道时的 id；新增填 0"},
        },
        "required": ["name", "ctype", "config"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"


class MessageClientDeleteTool(BaseTool):
    name = "message_client_delete"
    description = "删除消息通知渠道，需确认。"
    parameters = {
        "type": "object",
        "properties": {"cid": {"type": "integer", "description": "渠道 id（来自 message_client_list）"}},
        "required": ["cid"],
    }
    level = ToolLevel.WRITE
    permission = "setting:update"
