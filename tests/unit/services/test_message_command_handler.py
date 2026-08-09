"""MessageCommandHandler 单元测试."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.enums import SearchType
from app.services.system.message import MessageCommandHandler


class TestMessageCommandHandlerSearchCommands:
    """测试消息命令处理器对搜索/订阅类命令的路由."""

    @pytest.fixture
    def handler(self):
        search_handler = MagicMock()
        message = MagicMock()
        message.get_plugin_commands.return_value = {}
        thread_executor = MagicMock()
        return MessageCommandHandler(
            search_handler=search_handler,
            message=message,
            thread_executor=thread_executor,
        )

    @pytest.mark.parametrize(
        "msg",
        [
            "订阅 尼古猫猫",
            "搜索 尼古猫猫",
            "下载 尼古猫猫",
            "/rss 尼古猫猫",
            "/ssa 尼古猫猫",
        ],
    )
    def test_search_command_routes_to_search_handler(self, handler, msg):
        """中文订阅/搜索/下载命令及 /rss、/ssa 应路由到搜索服务."""
        handler.handle_message_job(msg, in_from=SearchType.WX, user_id="user1")

        handler._message.send_channel_msg.assert_called_once()
        call_args = handler._message.send_channel_msg.call_args
        assert "正在搜索/订阅" in call_args.kwargs.get("title", "")

        handler._thread_executor.submit.assert_called_once()
        _, args, _ = handler._thread_executor.submit.mock_calls[0]
        assert args[0] is handler._search_handler.handle
        assert args[1] == msg
        assert args[2] == SearchType.WX
        assert args[3] == "user1"

    def test_exact_command_routes_to_mapped_func(self, handler):
        """精确命令如 /sub 应执行映射函数而不是搜索."""
        subscription_monitor = MagicMock()
        handler._subscription_monitor = subscription_monitor

        handler.handle_message_job("/sub", in_from=SearchType.WX, user_id="user1")

        handler._thread_executor.submit.assert_called_once()
        _, args, _ = handler._thread_executor.submit.mock_calls[0]
        assert args[0] is subscription_monitor.run
        handler._search_handler.handle.assert_not_called()

    def test_plain_text_routes_to_search_handler(self, handler):
        """普通文本无命令前缀时也走搜索服务."""
        handler.handle_message_job("尼古猫猫", in_from=SearchType.WX, user_id="user1")

        handler._thread_executor.submit.assert_called_once()
        _, args, _ = handler._thread_executor.submit.mock_calls[0]
        assert args[0] is handler._search_handler.handle
        assert args[1] == "尼古猫猫"


class TestMessageCommandHandlerBuiltinCommands:
    """内置菜单命令注册完整性与分发测试."""

    @pytest.fixture
    def handler(self):
        search_handler = MagicMock()
        message = MagicMock()
        message.get_plugin_commands.return_value = {}
        thread_executor = MagicMock()
        handler = MessageCommandHandler(
            search_handler=search_handler,
            torrent_remover_service=MagicMock(),
            downloader_core=MagicMock(),
            sync_service=MagicMock(),
            filetransfer_service=MagicMock(),
            thread_executor=thread_executor,
            message=message,
            subscription_monitor=MagicMock(),
            rss_task_service=MagicMock(),
            subscribe_service=MagicMock(),
            site_service=MagicMock(),
            system_lifecycle=MagicMock(),
        )
        return handler

    def test_command_map_covers_all_builtin_commands(self, handler):
        """内置命令映射覆盖 COMMANDS 中全部非搜索类命令."""
        expected = {"/ptr", "/ptt", "/rst", "/sub", "/clr", "/utf", "/udt", "/sta"}
        assert expected == set(handler._command_map.keys())

    def test_sta_routes_to_site_service_not_search(self, handler):
        """/sta 应触发站点数据统计，不再落入媒体搜索."""
        handler.handle_message_job("/sta", in_from=SearchType.WX, user_id="user1")

        handler._thread_executor.submit.assert_called_once()
        _, args, _ = handler._thread_executor.submit.mock_calls[0]
        assert args[0] == handler._user_statistics
        handler._search_handler.handle.assert_not_called()

    def test_sta_executes_refresh_site_data(self, handler):
        """执行 /sta 命令调用 site_service.refresh_site_data_now."""
        handler._user_statistics()
        handler._site_service.refresh_site_data_now.assert_called_once()

    def test_udt_routes_to_restart_server(self, handler):
        """/udt 应调用 system_lifecycle.restart_server."""
        handler._command_map["/udt"]["func"]()
        handler._system_lifecycle.restart_server.assert_called_once()

    def test_utf_routes_to_unidentification(self, handler):
        """/utf 应触发重新识别未识别记录."""
        handler.handle_message_job("/utf", in_from=SearchType.WX, user_id="user1")

        handler._thread_executor.submit.assert_called_once()
        _, args, _ = handler._thread_executor.submit.mock_calls[0]
        assert args[0] == handler._unidentification
        handler._search_handler.handle.assert_not_called()

    def test_unidentification_calls_sync_service(self, handler):
        """重新识别收集未识别记录后调用 sync_service.re_identify_items."""
        record = MagicMock()
        record.PATH = "/downloads/unknown"
        record.ID = 7
        handler._filetransfer_service.get_transfer_unknown_paths.return_value = [record]

        handler._unidentification()

        handler._sync_service.re_identify_items.assert_called_once_with(flag="unidentification", ids=[7])

    def test_clr_clears_cache_system(self, handler):
        """/clr 清理缓存系统的全部缓存."""
        with patch("app.services.system.message.get_cache_manager") as mock_mgr:
            handler._clear_caches()
        mock_mgr.return_value.clear_all.assert_called_once()

    def test_missing_dependency_func_is_noop(self):
        """依赖未注入时命令函数为空操作且不抛异常."""
        handler = MessageCommandHandler()
        for cmd, command in handler._command_map.items():
            command["func"]()
        handler._truncate_rsshistory()
        handler._user_statistics()
        handler._unidentification()
