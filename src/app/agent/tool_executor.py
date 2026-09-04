"""工具执行器 — 校验 → 分级/确认 → 调度 handler

依赖经 ToolContext 类型化注入（替代旧 23 个位置参数 + deps dict）。
除内置工具外，支持“插件声明式工具”动态合并：插件 manifest 在 backend.tools 声明，
经 plugin_tools_provider 提供给执行器，执行时由 plugin_executor 派发到插件 backend.agent_tool()。
"""

import inspect
from collections.abc import Callable
from typing import Any

import log
from app.agent.sanitize import sanitize
from app.agent.tools.base import ToolLevel, ToolRegistry, ToolResult
from app.agent.tools.catalog import BUILTIN_TOOLS, HANDLERS
from app.agent.tools.context import ToolContext
from app.utils.json_utils import JsonUtils


def _plugin_tool_schema(spec: dict) -> dict:
    """插件工具 spec → 供模型使用的 schema（与内置 BaseTool.to_schema 一致）"""
    return {
        "name": spec.get("name", ""),
        "description": spec.get("description", ""),
        "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
        "level": spec.get("level") or ToolLevel.READ.value,
    }


class ToolExecutor:
    """工具执行器 — Agent 工具调用的唯一入口"""

    def __init__(
        self,
        ctx: ToolContext,
        registry: ToolRegistry | None = None,
        plugin_tools_provider: Callable[[], list[dict]] | None = None,
        plugin_executor: Callable[[str, str, dict], Any] | None = None,
    ):
        self._ctx = ctx
        self._registry = registry or ToolRegistry(BUILTIN_TOOLS)
        self._handlers: dict[str, Callable] = dict(HANDLERS)
        # 插件工具能力：provider 返回 [{plugin_id,name,description,parameters,level,permission}, …]
        self._plugin_tools_provider = plugin_tools_provider
        self._plugin_executor = plugin_executor

    # ---------------------------------------------------------------- 工具合并

    def _plugin_tools(self) -> dict[str, dict]:
        if not self._plugin_tools_provider:
            return {}
        try:
            specs = self._plugin_tools_provider() or []
        except Exception as e:  # noqa: BLE001
            log.warn(f"[ToolExecutor]读取插件工具失败: {e}")
            return {}
        return {str(s.get("name")): s for s in specs if s.get("name")}

    def _plugin_schema(self, name: str) -> dict | None:
        spec = self._plugin_tools().get(name)
        return _plugin_tool_schema(spec) if spec else None

    def list_tools(self) -> list[dict]:
        schemas = self._registry.list_tools()
        schemas.extend(_plugin_tool_schema(s) for s in self._plugin_tools().values())
        return schemas

    def get_schema(self, name: str) -> dict | None:
        return self._registry.get_schema(name) or self._plugin_schema(name)

    def tool_names(self) -> list[str]:
        return list(self._registry.tool_names()) + list(self._plugin_tools().keys())

    # ---------------------------------------------------------------- 执行

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
        if self._registry.get_tool(tool_name):
            return self._execute_builtin(
                tool_name, arguments, confirmed, session_id, user_id, user_permissions, channel
            )
        plugin_tools = self._plugin_tools()
        spec = plugin_tools.get(tool_name)
        if not spec or not self._plugin_executor:
            return ToolResult(success=False, error=f"未知工具: {tool_name}")
        return self._execute_plugin(spec, tool_name, arguments, confirmed, user_permissions)

    def _execute_builtin(
        self,
        tool_name: str,
        arguments: dict | str,
        confirmed: bool,
        session_id: str,
        user_id: str,
        user_permissions: list[str] | None,
        channel: str,
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

    def _execute_plugin(
        self,
        spec: dict,
        tool_name: str,
        arguments: dict | str,
        confirmed: bool,
        user_permissions: list[str] | None,
    ) -> ToolResult:
        args = arguments if isinstance(arguments, dict) else {}
        if isinstance(arguments, str):
            try:
                args = JsonUtils.loads(arguments)
            except (ValueError, TypeError) as e:
                return ToolResult(success=False, error=f"参数格式错误: {e}")
        schema = _plugin_tool_schema(spec)
        permission = spec.get("permission") or ""
        level = spec.get("level") or ToolLevel.READ.value
        error = ToolRegistry._validate(spec.get("parameters") or {"type": "object", "properties": {}}, args)
        if error:
            return ToolResult(success=False, error=error)
        if permission and user_permissions is not None and permission not in user_permissions:
            return ToolResult(success=False, error=f"无权限执行该操作，需要权限: {permission}")
        if level == ToolLevel.DANGEROUS.value and not confirmed:
            return ToolResult(
                success=True,
                need_confirm=True,
                data={
                    "tool": tool_name,
                    "arguments": args,
                    "message": f"危险操作需确认：{schema['description'] or tool_name}",
                },
            )
        try:
            log.info(f"[ToolExecutor]执行插件工具: {tool_name}({sanitize(JsonUtils.dumps(args))})")
            executor = self._plugin_executor
            if executor is None:
                return ToolResult(success=False, error=f"插件工具未接入执行器: {tool_name}")
            raw = executor(spec["plugin_id"], tool_name, args)
            return self._to_tool_result(raw)
        except Exception as e:
            log.error(f"[ToolExecutor]插件工具 {tool_name} 执行失败: {e}")
            return ToolResult(success=False, error=f"插件工具执行失败: {e}")

    @staticmethod
    def _to_tool_result(raw: Any) -> ToolResult:
        """插件 backend.agent_tool 返回值 → ToolResult

        约定：{success, data, error}；未含 success/error 键时按原样作为成功 data。
        """
        if isinstance(raw, ToolResult):
            return raw
        if isinstance(raw, dict):
            if "success" in raw or "error" in raw:
                ok = bool(raw.get("success"))
                return ToolResult(
                    success=ok,
                    data=raw.get("data") if ok else None,
                    error=raw.get("error") or ("" if ok else "插件工具执行失败"),
                )
            return ToolResult(success=True, data=raw)
        if raw is None:
            return ToolResult(success=True, data=None)
        return ToolResult(success=True, data={"result": raw})

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
