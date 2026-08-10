"""工具基础类型与注册表

无全局可变状态：ToolRegistry 为实例，由 ToolExecutor 持显式目录（catalog.BUILTIN_TOOLS）构造。
schemas/ 只放零依赖 Schema 定义；handlers/ 放执行逻辑（经 ToolContext 依赖 Services 门面）。
"""

from abc import ABC
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from app.utils.json_utils import JsonUtils


class ToolLevel(str, Enum):
    """工具分级：read 只读 / write 写操作 / dangerous 需确认"""

    READ = "read"
    WRITE = "write"
    DANGEROUS = "dangerous"


@dataclass
class ToolResult:
    """工具执行结果 — data 恒为结构化 dict/list，失败恒走 error"""

    success: bool
    data: dict | list | None = None
    error: str = ""
    need_confirm: bool = False


class BaseTool(ABC):
    """工具 Schema 定义基类"""

    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)
    level: ToolLevel = ToolLevel.READ
    permission: str = ""

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "level": self.level.value,
        }


class ToolRegistry:
    """工具 Schema 注册表（实例化，显式注入工具目录）"""

    def __init__(self, tools: Iterable[BaseTool]):
        self._tools = {t.name: t for t in tools if t.name}

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def get_schema(self, name: str) -> dict | None:
        tool = self.get_tool(name)
        return tool.to_schema() if tool else None

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    @staticmethod
    def _validate(schema: dict, arguments: dict) -> str | None:
        """基础参数校验：返回错误消息或 None"""
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in arguments or arguments.get(key) is None:
                return f"缺少必填参数: {key}"
        for key, value in arguments.items():
            if key not in properties:
                return f"未知参数: {key}"
            prop = properties.get(key, {})
            if value is None:
                continue
            expected = prop.get("type")
            if expected == "string" and not isinstance(value, str):
                return f"参数 {key} 应为字符串"
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                return f"参数 {key} 应为整数"
            if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                return f"参数 {key} 应为数字"
            if expected == "boolean" and not isinstance(value, bool):
                return f"参数 {key} 应为布尔值"
            if expected == "array" and not isinstance(value, list):
                return f"参数 {key} 应为数组"
            if expected == "object" and not isinstance(value, dict):
                return f"参数 {key} 应为对象"
            if "enum" in prop and value not in prop["enum"]:
                return f"参数 {key} 应为 {prop['enum']} 之一"
        return None

    def validate(self, tool_name: str, arguments: dict | str) -> ToolResult:
        """解析并校验参数；成功时 data 为参数字典"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(success=False, error=f"未知工具: {tool_name}")
        if isinstance(arguments, str):
            try:
                arguments = JsonUtils.loads(arguments)
            except (ValueError, TypeError) as e:
                return ToolResult(success=False, error=f"参数格式错误: {e}")
        if not isinstance(arguments, dict):
            return ToolResult(success=False, error="参数必须是对象")
        error = self._validate(tool.parameters, arguments)
        if error:
            return ToolResult(success=False, error=error)
        return ToolResult(success=True, data=arguments)
