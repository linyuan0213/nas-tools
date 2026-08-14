"""Tests for app.message package."""

from unittest.mock import MagicMock, patch

import pytest

from app.domain.enums import SearchType
from app.domain.mediatypes import MediaType
from app.message.core.client_manager import ClientManager, parse_client_config
from app.message.core.command_manager import CommandManager
from app.message.core.dispatcher import MessageDispatcher
from app.message.core.message_builder import MessageBuilder
from app.message.core.template_engine import TemplateEngine
from app.message.message import Message


class TestTemplateEngine:
    """Test suite for TemplateEngine."""

    def test_render_template_empty(self):
        engine = TemplateEngine()
        assert engine.render_template("", {}) is None
        assert engine.render_template(None, {}) is None

    def test_render_template_simple(self):
        engine = TemplateEngine()
        result = engine.render_template("Hello {{ name }}", {"name": "World"})
        assert result == "Hello World"

    def test_render_template_with_filters(self):
        engine = TemplateEngine()
        result = engine.render_template("{{ value | default('fallback', true) }}", {})
        assert result == "fallback"
        result = engine.render_template("{{ value | yesno }}", {"value": True})
        assert result == "是"

    def test_render_template_escape_newline(self):
        engine = TemplateEngine()
        result = engine.render_template("a\\nb", {})
        assert result == "a\nb"

    def test_apply_client_template_no_templates(self):
        # 客户端无模板配置或空模板：回退默认模板（非纯文本）
        engine = TemplateEngine()
        client = {"name": "test", "templates": None}
        title, text = engine.apply_client_template(client, "site_message", {"title": "T", "text": "B"})
        assert title is not None
        assert "T" in title

    def test_apply_client_template_empty_dict(self):
        # 空模板配置 {} 同样回退默认模板（Web 客户端场景）
        engine = TemplateEngine()
        client = {"name": "test", "templates": {}}
        title, text = engine.apply_client_template(client, "site_message", {"title": "T", "text": "B"})
        assert title is not None
        assert "T" in title

    def test_apply_client_template_unknown_type(self):
        # 无此类型且无默认模板 → None
        engine = TemplateEngine()
        client = {"name": "test", "templates": None}
        assert engine.apply_client_template(client, "no_such_type", {}) == (None, None)

    def test_apply_client_template_with_default(self):
        from app.message.templates import DEFAULT_MESSAGE_TEMPLATES

        engine = TemplateEngine()
        client = {"name": "test", "templates": {"other_type": {}}}
        DEFAULT_MESSAGE_TEMPLATES["test_type"] = {"title": "T {{x}}", "text": "B {{x}}"}
        title, text = engine.apply_client_template(client, "test_type", {"x": "1"})
        assert title == "T 1"
        assert text == "B 1"
        del DEFAULT_MESSAGE_TEMPLATES["test_type"]


class TestClientManager:
    """Test suite for ClientManager."""

    def test_parse_client_config(self):
        config = MagicMock()
        config.ID = 1
        config.NAME = "test"
        config.TYPE = "telegram"
        config.CONFIG = '{"token": "abc"}'
        config.TEMPLATES = ""
        config.SWITCHES = '["download_start"]'
        config.INTERACTIVE = True
        config.ENABLED = True
        result = parse_client_config(config)
        assert result["id"] == 1
        assert result["name"] == "test"
        assert result["config"]["token"] == "abc"
        assert "download_start" in result["switches"]

    def test_parse_client_config_invalid_json(self):
        config = MagicMock()
        config.ID = 1
        config.NAME = "test"
        config.TYPE = "telegram"
        config.CONFIG = "not-json"
        config.TEMPLATES = ""
        config.SWITCHES = ""
        config.INTERACTIVE = False
        config.ENABLED = True
        result = parse_client_config(config)
        assert result["config"] == {"interactive": False}

    def test_get_message_client_info_empty(self):
        mock_repo = MagicMock()
        mock_repo.get_message_client.return_value = []
        manager = ClientManager(config_repo=mock_repo)
        assert manager.get_message_client_info() == {}

    def test_delete_message_client(self):
        mock_repo = MagicMock()
        mock_repo.delete_message_client.return_value = True
        manager = ClientManager(config_repo=mock_repo)
        result = manager.delete_message_client(1)
        assert result is True
        mock_repo.delete_message_client.assert_called_once_with(cid=1)

    def test_insert_message_client(self):
        mock_repo = MagicMock()
        mock_repo.insert_message_client.return_value = 42
        manager = ClientManager(config_repo=mock_repo)
        result = manager.insert_message_client(
            name="tg", ctype="telegram", config="{}", switches=[], interactive=True, enabled=True
        )
        assert result is True
        mock_repo.insert_message_client.assert_called_once()

    def test_get_status_missing_params(self):
        manager = ClientManager()
        assert manager.get_status() is False
        assert manager.get_status(ctype="telegram") is False

    def test_get_status_success(self):
        manager = ClientManager()
        mock_client = MagicMock()
        mock_client.send_msg.return_value = (True, "ok")
        with patch("app.message.core.client_manager.ClientRegistry.build", return_value=mock_client):
            assert manager.get_status(ctype="telegram", config={"token": "x"}) is True

    def test_get_status_failure(self):
        manager = ClientManager()
        mock_client = MagicMock()
        mock_client.send_msg.return_value = (False, "err")
        with patch("app.message.core.client_manager.ClientRegistry.build", return_value=mock_client):
            assert manager.get_status(ctype="telegram", config={}) is False

    def test_ensure_loaded_refreshes_when_interactive_changed(self):
        """数据库中 interactive 标志变更后应重新加载客户端."""
        client_config = MagicMock()
        client_config.ID = 1
        client_config.NAME = "test"
        client_config.TYPE = "test"
        client_config.CONFIG = '{"token": "x"}'
        client_config.TEMPLATES = ""
        client_config.SWITCHES = ""
        client_config.INTERACTIVE = False
        client_config.ENABLED = True

        mock_repo = MagicMock()
        mock_repo.get_message_client.return_value = [client_config]
        with (
            patch("app.message.core.client_manager.ClientManager._get_search_type", return_value=SearchType.TG),
            patch("app.message.core.client_manager.ClientRegistry.build"),
        ):
            manager = ClientManager(config_repo=mock_repo)
            assert SearchType.TG not in manager.active_interactive_clients

            # 模拟数据库中开启交互
            client_config.INTERACTIVE = True
            assert SearchType.TG in manager.active_interactive_clients

    def test_ensure_loaded_removes_disabled_clients(self):
        """数据库中禁用的客户端应从内存中移除."""
        client_config = MagicMock()
        client_config.ID = 1
        client_config.NAME = "test"
        client_config.TYPE = "test"
        client_config.CONFIG = '{"token": "x"}'
        client_config.TEMPLATES = ""
        client_config.SWITCHES = ""
        client_config.INTERACTIVE = True
        client_config.ENABLED = True

        mock_repo = MagicMock()
        mock_repo.get_message_client.return_value = [client_config]
        with (
            patch("app.message.core.client_manager.ClientManager._get_search_type", return_value=SearchType.TG),
            patch("app.message.core.client_manager.ClientRegistry.build"),
        ):
            manager = ClientManager(config_repo=mock_repo)
            assert SearchType.TG in manager.active_interactive_clients

            # 模拟数据库中禁用
            client_config.ENABLED = False
            assert SearchType.TG not in manager.active_interactive_clients

    def test_get_interactive_client_by_enum(self):
        """使用 SearchType 枚举应能查到以字符串 search_type 为 key 的客户端."""
        client_config = MagicMock()
        client_config.ID = 1
        client_config.NAME = "wechat"
        client_config.TYPE = "wechat"
        client_config.CONFIG = '{"corpid": "x"}'
        client_config.TEMPLATES = ""
        client_config.SWITCHES = ""
        client_config.INTERACTIVE = True
        client_config.ENABLED = True

        mock_repo = MagicMock()
        mock_repo.get_message_client.return_value = [client_config]
        with (
            patch("app.message.core.client_manager.ClientManager._get_search_type", return_value="WX"),
            patch("app.message.core.client_manager.ClientRegistry.build", return_value=MagicMock()),
        ):
            manager = ClientManager(config_repo=mock_repo)
            entry = manager.get_interactive_client(SearchType.WX)
            assert entry is not None
            assert entry["name"] == "wechat"

    def test_get_interactive_client_by_string(self):
        """使用字符串 search_type 也应正常查询."""
        client_config = MagicMock()
        client_config.ID = 1
        client_config.NAME = "wechat"
        client_config.TYPE = "wechat"
        client_config.CONFIG = '{"corpid": "x"}'
        client_config.TEMPLATES = ""
        client_config.SWITCHES = ""
        client_config.INTERACTIVE = True
        client_config.ENABLED = True

        mock_repo = MagicMock()
        mock_repo.get_message_client.return_value = [client_config]
        with (
            patch("app.message.core.client_manager.ClientManager._get_search_type", return_value="WX"),
            patch("app.message.core.client_manager.ClientRegistry.build", return_value=MagicMock()),
        ):
            manager = ClientManager(config_repo=mock_repo)
            entry = manager.get_interactive_client("WX")
            assert entry is not None
            assert entry["name"] == "wechat"


class TestCommandManager:
    """Test suite for CommandManager."""

    def test_register_and_get_commands(self):
        manager = CommandManager()
        manager.register_command("test", "test desc", lambda: None, plugin_id="p1")
        cmds = manager.get_commands()
        assert "/test" in cmds
        assert cmds["/test"] == "test desc"

    def test_unregister_command(self):
        manager = CommandManager()
        manager.register_command("test", "desc", lambda: None)
        manager.unregister_command("test")
        assert "/test" not in manager.get_commands()

    def test_clear_plugin_commands(self):
        manager = CommandManager()
        manager.register_command("a", "desc", lambda: None, plugin_id="p1")
        manager.register_command("b", "desc", lambda: None, plugin_id="p2")
        manager.clear_plugin_commands("p1")
        cmds = manager.get_plugin_commands()
        assert "/a" not in cmds
        assert "/b" in cmds

    def test_register_command_adds_slash(self):
        manager = CommandManager()
        manager.register_command("cmd", "desc", lambda: None)
        assert "/cmd" in manager.get_commands()


class TestMessageDispatcher:
    """Test suite for MessageDispatcher."""

    def test_send_channel_msg_web(self):
        client_mgr = MagicMock()
        msg_center = MagicMock()
        dispatcher = MessageDispatcher(client_mgr, msg_center)
        result = dispatcher.send_channel_msg(SearchType.WEB, "title", "text")
        assert result is True
        msg_center.insert_system_message.assert_called_once_with(title="title", content="text")

    def test_send_channel_msg_no_client(self):
        client_mgr = MagicMock()
        client_mgr.get_interactive_client.return_value = None
        msg_center = MagicMock()
        dispatcher = MessageDispatcher(client_mgr, msg_center)
        result = dispatcher.send_channel_msg(SearchType.TG, "title", "text")
        assert result is False
        client_mgr.get_interactive_client.assert_called_once_with(SearchType.TG)

    def test_get_search_types(self):
        dispatcher = MessageDispatcher(MagicMock(), MagicMock())
        types = dispatcher.get_search_types()
        assert SearchType.WX in types
        assert SearchType.TG in types

    def test_sendmsg_no_client(self):
        dispatcher = MessageDispatcher(MagicMock(), MagicMock())
        result = dispatcher.sendmsg(None, "title")
        assert result is False

    def test_send_list_msg_no_client(self):
        dispatcher = MessageDispatcher(MagicMock(), MagicMock())
        result = dispatcher.send_list_msg(None, [], "", "")
        assert result is False


class TestMessageBuilder:
    """Test suite for MessageBuilder."""

    def test_send_site_signin_message_empty(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_site_signin_message([])

    def test_send_site_signin_message(self):
        client_mgr = MagicMock()
        client = {"id": 1, "name": "tg", "switches": ["site_signin"]}
        client_mgr.active_clients = [client]
        dispatcher = MagicMock()
        msg_center = MagicMock()
        builder = MessageBuilder(client_mgr, dispatcher, msg_center)
        builder.send_site_signin_message(["site1 ok"])
        msg_center.insert_system_message.assert_called_once()
        dispatcher.sendmsg.assert_called_once()

    def test_send_site_message_no_title(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_site_message(title=None)

    def test_send_transfer_fail_message_empty(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_transfer_fail_message("", 0, "")

    def test_send_auto_remove_torrents_message_empty(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_auto_remove_torrents_message("", "")

    def test_send_rss_finished_movie_skips(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        media = MagicMock()
        media.type = MediaType.MOVIE
        builder.send_rss_finished_message(media)

    def test_send_mediaserver_message_empty(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_mediaserver_message({}, "Emby", None)

    def test_send_plugin_message_no_title(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_plugin_message("")

    def test_send_custom_message_no_title(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_custom_message(None, "")

    def test_send_user_statistics_message_empty(self):
        builder = MessageBuilder(MagicMock(), MagicMock(), MagicMock())
        builder.send_user_statistics_message([])


class TestMessageFacade:
    """Test suite for Message Facade."""

    @pytest.fixture
    def msg(self):
        """Provide a Message instance with mocked internals."""
        with (
            patch("app.message.message.get_domain", return_value="http://test"),
            patch("app.message.message.MessageCenter"),
            patch("app.message.message.ClientManager") as mock_cm,
            patch("app.message.message.CommandManager"),
            patch("app.message.message.TemplateEngine"),
            patch("app.message.message.MessageDispatcher") as mock_disp,
            patch("app.message.message.MessageBuilder") as mock_builder,
        ):
            mock_cm_instance = MagicMock()
            mock_cm.return_value = mock_cm_instance
            mock_disp_instance = MagicMock()
            mock_disp.return_value = mock_disp_instance
            mock_builder_instance = MagicMock()
            mock_builder.return_value = mock_builder_instance
            m = Message(apikey_service=MagicMock())
            m._client_manager = mock_cm_instance
            m._dispatcher = mock_disp_instance
            m._builder = mock_builder_instance
            yield m

    def test_active_clients_property(self, msg):
        _ = msg.active_clients

    def test_get_commands_delegates(self, msg):
        msg._command_manager.get_commands.return_value = {"/cmd": "desc"}
        result = msg.get_commands()
        assert "/cmd" in result

    def test_register_command_delegates(self, msg):
        msg.register_command("cmd", "desc", lambda: None)
        msg._command_manager.register_command.assert_called_once()

    def test_get_search_types_delegates(self, msg):
        msg._dispatcher.get_search_types.return_value = [SearchType.WX]
        result = msg.get_search_types()
        assert SearchType.WX in result

    def test_send_channel_msg_delegates(self, msg):
        msg._dispatcher.send_channel_msg.return_value = True
        result = msg.send_channel_msg(SearchType.WEB, "title", "text")
        assert result is True

    def test_send_download_message_delegates(self, msg):
        msg.send_download_message("from", MagicMock())
        msg._builder.send_download_message.assert_called_once()

    def test_send_transfer_movie_message_delegates(self, msg):
        msg.send_transfer_movie_message("from", MagicMock(), 0, False)
        msg._builder.send_transfer_movie_message.assert_called_once()

    def test_send_site_signin_message_delegates(self, msg):
        msg.send_site_signin_message(["ok"])
        msg._builder.send_site_signin_message.assert_called_once_with(["ok"])

    def test_delete_message_client_delegates(self, msg):
        msg._client_manager.delete_message_client.return_value = True
        result = msg.delete_message_client(1)
        assert result is True

    def test_insert_message_client_delegates(self, msg):
        msg._client_manager.insert_message_client.return_value = True
        result = msg.insert_message_client("n", "t", "{}", [], True, True)
        assert result is True

    def test_get_status_delegates(self, msg):
        msg._client_manager.get_status.return_value = True
        result = msg.get_status("telegram", {})
        assert result is True
