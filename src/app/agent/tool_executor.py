"""工具执行器 — 校验 → 分级/确认 → 调度 handler

依赖经 ToolContext 类型化注入（替代旧 23 个位置参数 + deps dict）。
"""

import inspect
from collections.abc import Callable

import log
from app.agent.sanitize import sanitize
from app.agent.tools.base import ToolLevel, ToolRegistry, ToolResult
from app.agent.tools.catalog import BUILTIN_TOOLS, HANDLERS
from app.agent.tools.context import ToolContext
from app.utils.json_utils import JsonUtils


class ToolExecutor:
    """工具执行器 — Agent 工具调用的唯一入口"""

    def __init__(self, ctx: ToolContext, registry: ToolRegistry | None = None):
        self._ctx = ctx
        self._registry = registry or ToolRegistry(BUILTIN_TOOLS)
        self._handlers: dict[str, Callable] = dict(HANDLERS)

    def list_tools(self) -> list[dict]:
        return self._registry.list_tools()

    def get_schema(self, name: str) -> dict | None:
        return self._registry.get_schema(name)

    def tool_names(self) -> list[str]:
        return self._registry.tool_names()

    def execute(
        self,
        tool_name: str,
        arguments: dict | str,
        *,
        confirmed: bool = False,
        session_id: str = "",
        user_id: str = "",
        user_permissions: list[str] | None = None,
        channel: str = "",
    ) -> ToolResult:
        check = self._registry.validate(tool_name, arguments)
        if not check.success:
            return check
        args = check.data if isinstance(check.data, dict) else {}
        tool = self._registry.get_tool(tool_name)
        handler = self._handlers.get(tool_name)
        if not tool or not handler:
            return ToolResult(success=False, error=f"工具未实现: {tool_name}")
        if tool.permission and user_permissions is not None and tool.permission not in user_permissions:
            return ToolResult(success=False, error=f"无权限执行该操作，需要权限: {tool.permission}")
        if tool.level == ToolLevel.DANGEROUS and not confirmed:
            return ToolResult(
                success=True,
                need_confirm=True,
                data={"tool": tool_name, "arguments": args, "message": f"危险操作需确认：{tool.description}"},
            )
        kwargs = self._build_kwargs(handler, args, confirmed, session_id, user_id, channel)
        try:
            log.info(f"[ToolExecutor]执行工具: {tool_name}({sanitize(JsonUtils.dumps(args))})")
            return handler(self._ctx, **kwargs)
        except Exception as e:
            log.error(f"[ToolExecutor]工具 {tool_name} 执行失败: {e}")
            return ToolResult(success=False, error=f"执行失败: {e}")

    @staticmethod
    def _build_kwargs(
        handler: Callable, args: dict, confirmed: bool, session_id: str, user_id: str, channel: str
    ) -> dict:
        """按 handler 签名注入保留参数（confirmed/session_id/user_id/channel）"""
        kwargs = dict(args)
        params = inspect.signature(handler).parameters
        for key, value in {
            "confirmed": confirmed,
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
        }.items():
            if key in params:
                kwargs[key] = value
        return kwargs
