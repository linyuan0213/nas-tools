"""插件声明式 Agent 工具 — ToolExecutor 动态合并与派发单元测试"""

from typing import cast

from app.agent.tool_executor import ToolExecutor
from app.agent.tools.context import ToolContext
from app.schemas.plugin import PluginManifest

_CTX = cast(ToolContext, None)

_PLUGIN_TOOLS = [
    {
        "plugin_id": "demo_plugin",
        "name": "demo_echo",
        "description": "回显参数（插件示例工具）",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
        "level": "read",
    },
    {
        "plugin_id": "demo_plugin",
        "name": "demo_remove",
        "description": "危险插件工具示例",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        "level": "dangerous",
    },
]


def _make_executor(executor=None, tools=None, provider=None):
    return ToolExecutor(
        ctx=_CTX,
        plugin_tools_provider=provider or (lambda: tools or _PLUGIN_TOOLS),
        plugin_executor=executor,
    )


class TestPluginToolMerge:
    def test_list_tools_merges_plugin_schemas(self):
        ex = _make_executor(executor=lambda pid, name, args: {"success": True, "data": {}})
        names = [t["name"] for t in ex.list_tools()]
        assert "system_status" in names  # 内置仍在
        assert "demo_echo" in names
        schema = ex.get_schema("demo_echo")
        assert schema is not None and schema["level"] == "read"
        assert "demo_echo" in ex.tool_names()

    def test_unknown_tool_rejected(self):
        ex = _make_executor(executor=lambda pid, name, args: {"success": True, "data": {}})
        result = ex.execute("no_such_tool", {})
        assert not result.success
        assert "未知工具" in result.error


class TestPluginToolExecute:
    def test_read_dispatch_and_result_convert(self):
        calls = []

        def fake(plugin_id, name, args):
            calls.append((plugin_id, name, args))
            return {"success": True, "data": {"echo": args.get("text")}}

        ex = _make_executor(executor=fake)
        result = ex.execute("demo_echo", {"text": "hello"})
        assert result.success
        assert result.data == {"echo": "hello"}
        assert calls == [("demo_plugin", "demo_echo", {"text": "hello"})]

    def test_raw_dict_result_treated_as_success_data(self):
        ex = _make_executor(executor=lambda pid, name, args: {"text": args.get("text")})
        result = ex.execute("demo_echo", {"text": "x"})
        assert result.success
        assert result.data == {"text": "x"}

    def test_error_dict_result(self):
        ex = _make_executor(executor=lambda pid, name, args: {"success": False, "error": "插件内部失败"})
        result = ex.execute("demo_echo", {"text": "x"})
        assert not result.success
        assert "插件内部失败" in result.error

    def test_dangerous_requires_confirm_then_runs(self):
        calls = []

        def fake(pid, name, args):
            calls.append(name)
            return {"success": True, "data": {}}

        ex = _make_executor(executor=fake)
        blocked = ex.execute("demo_remove", {"id": "1"})
        assert blocked.need_confirm
        assert calls == []
        ok = ex.execute("demo_remove", {"id": "1"}, confirmed=True)
        assert ok.success
        assert calls == ["demo_remove"]

    def test_permission_enforced(self):
        def fake(pid, name, args):
            return {"success": True, "data": {}}

        tools = [dict(_PLUGIN_TOOLS[0], permission="demo:manage")]
        ex = _make_executor(executor=fake, tools=tools)
        denied = ex.execute("demo_echo", {"text": "x"}, user_permissions=["setting:view"])
        assert not denied.success
        assert "无权限" in denied.error
        ok = ex.execute("demo_echo", {"text": "x"}, user_permissions=["demo:manage"])
        assert ok.success


class TestPluginManifestTools:
    def test_manifest_tools_roundtrip(self):
        raw = {
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "backend": {
                "entry": "plugin:DemoPlugin",
                "tools": [
                    {
                        "name": "demo_echo",
                        "description": "回显",
                        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
                        "level": "write",
                        "permission": "demo:manage",
                    }
                ],
            },
            "frontend": {"settings": {"component": "", "fields": []}, "routes": [], "slots": []},
        }
        manifest = PluginManifest.from_dict(raw)
        assert len(manifest.backend.tools) == 1
        tool = manifest.backend.tools[0]
        assert tool.name == "demo_echo"
        assert tool.level == "write"
        assert tool.permission == "demo:manage"
        restored = PluginManifest.from_dict(manifest.to_dict())
        assert restored.backend.tools[0].parameters == {"type": "object", "properties": {"text": {"type": "string"}}}
