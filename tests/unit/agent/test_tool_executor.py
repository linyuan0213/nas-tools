"""ToolExecutor 单元测试（新工具层：ToolContext + 分级 + 确认流）"""

from unittest.mock import MagicMock

import pytest

from app.agent.tool_executor import ToolExecutor
from app.agent.tools.base import ToolRegistry
from app.agent.tools.catalog import BUILTIN_TOOLS, HANDLERS
from app.agent.tools.context import ToolContext


def _ctx(**overrides) -> ToolContext:
    defaults = dict(
        search_orchestrator=MagicMock(),
        searcher=MagicMock(),
        download_service=MagicMock(),
        downloader_core=MagicMock(),
        subscribe_service=MagicMock(),
        media_service=MagicMock(),
        media_info_service=MagicMock(),
        filetransfer_service=MagicMock(),
        scheduler_service=MagicMock(),
        system_info_service=MagicMock(),
        event_bus=MagicMock(),
        retriever=None,
        conversation_store=None,
    )
    defaults.update(overrides)
    return ToolContext(**defaults)


def _data(result) -> dict:
    """窄化 ToolResult.data 为 dict"""
    assert isinstance(result.data, dict)
    return result.data


@pytest.fixture
def executor():
    return ToolExecutor(ctx=_ctx())


class TestCatalog:
    def test_all_tools_have_handlers(self):
        names = {t.name for t in BUILTIN_TOOLS}
        assert names == set(HANDLERS.keys())
        assert len(names) == 65

    def test_tool_count_and_levels(self):
        registry = ToolRegistry(BUILTIN_TOOLS)
        schemas = registry.list_tools()
        assert len(schemas) == 65
        for s in schemas:
            assert s["level"] in ("read", "write", "dangerous")


class TestValidation:
    def test_unknown_tool(self, executor):
        result = executor.execute("not_exist", {})
        assert not result.success
        assert "未知工具" in result.error

    def test_missing_required_param(self, executor):
        result = executor.execute("media_search", {})
        assert not result.success
        assert "缺少必填参数" in result.error

    def test_unknown_param(self, executor):
        result = executor.execute("media_search", {"query": "x", "bad": 1})
        assert not result.success
        assert "未知参数" in result.error

    def test_type_mismatch(self, executor):
        result = executor.execute("media_search", {"query": 123})
        assert not result.success
        assert "应为字符串" in result.error

    def test_enum_validation(self, executor):
        result = executor.execute("download_control", {"action": "explode", "ids": ["a"]})
        assert not result.success

    def test_string_arguments_parsed(self, executor):
        orchestrator = executor._ctx.search_orchestrator
        orchestrator.orchestrate.return_value = (None, {}, 0, 0)
        result = executor.execute("media_search", '{"query": "流浪地球"}')
        assert result.success


class TestLevelsAndConfirm:
    def test_dangerous_needs_confirm(self, executor):
        result = executor.execute("subscribe_delete", {"sub_id": 1})
        assert result.success
        assert result.need_confirm
        executor._ctx.subscribe_service.delete_subscribe.assert_not_called()

    def test_dangerous_confirmed_executes(self, executor):
        result = executor.execute("subscribe_delete", {"sub_id": 1}, confirmed=True)
        assert result.success
        assert not result.need_confirm
        executor._ctx.subscribe_service.delete_subscribe.assert_called_once()

    def test_download_remove_needs_confirm_inline(self, executor):
        result = executor.execute("download_control", {"action": "remove", "ids": ["h1"]})
        assert result.need_confirm
        executor._ctx.downloader_core.delete_torrents.assert_not_called()

    def test_download_remove_confirmed(self, executor):
        result = executor.execute("download_control", {"action": "remove", "ids": ["h1"]}, confirmed=True)
        assert result.success
        executor._ctx.downloader_core.delete_torrents.assert_called_once_with(ids=["h1"], delete_file=False)

    def test_permission_required_for_write_tool(self, executor):
        """写工具未授予权限时拒绝执行"""
        result = executor.execute("subscribe_delete", {"sub_id": 1}, confirmed=True, user_permissions=["agent:view"])
        assert not result.success
        assert "无权限" in result.error
        executor._ctx.subscribe_service.delete_subscribe.assert_not_called()

    def test_permission_granted_executes(self, executor):
        result = executor.execute(
            "subscribe_delete",
            {"sub_id": 1},
            confirmed=True,
            user_permissions=["agent:view", "subscription:manage"],
        )
        assert result.success
        executor._ctx.subscribe_service.delete_subscribe.assert_called_once()

    def test_permission_skipped_when_not_provided(self, executor):
        """消息渠道等未传权限列表时不做拦截（兼容旧路径）"""
        result = executor.execute("subscribe_delete", {"sub_id": 1}, confirmed=True)
        assert result.success

    def test_read_tool_no_permission_required(self, executor):
        executor._ctx.scheduler_service.get_jobs.return_value = MagicMock(model_dump=lambda: {"jobs": []})
        result = executor.execute("scheduler_list", {}, user_permissions=["agent:view"])
        assert result.success


class TestDispatch:
    def test_media_search_calls_orchestrator(self, executor):
        orchestrator = executor._ctx.search_orchestrator
        orchestrator.orchestrate.return_value = (None, {}, 0, 0)
        result = executor.execute("media_search", {"query": "流浪地球"})
        assert result.success
        assert _data(result)["total"] == 0
        orchestrator.orchestrate.assert_called_once()

    def test_kb_search_disabled(self, executor):
        result = executor.execute("kb_search", {"query": "如何配置"})
        assert not result.success
        assert "未启用" in result.error

    def test_handler_exception_returns_error(self, executor):
        executor._ctx.download_service.get_downloading_with_media_info.side_effect = RuntimeError("boom")
        result = executor.execute("download_list", {})
        assert not result.success
        assert "boom" in result.error

    def test_memory_clear_disabled(self, executor):
        result = executor.execute("memory_clear", {})
        assert not result.success
        assert "未启用" in result.error

    def test_memory_clear_with_store(self):
        store = MagicMock()
        executor = ToolExecutor(ctx=_ctx(conversation_store=store))
        result = executor.execute("memory_clear", {}, session_id="s1", user_id="u1")
        assert result.success
        store.clear_session.assert_called_once_with(session_id="s1", user_id="u1")
