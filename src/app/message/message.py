"""Message - 消息业务 Facade.

保留与原 Message 兼容的公共 API，客户端管理、命令管理、
模板渲染、消息调度、业务构建委托给独立组件.
"""

from typing import Any

from app.message.core.agent_dispatcher import AgentEnhancingDispatcher
from app.message.core.client_manager import ClientManager
from app.message.core.command_manager import CommandManager
from app.message.core.dispatcher import MessageDispatcher
from app.message.core.message_builder import MessageBuilder
from app.message.core.template_engine import TemplateEngine
from app.message.message_center import MessageCenter
from app.services.apikey_service import APIKeyService
from app.utils.config_tools import get_domain


class Message:
    """消息业务 Facade，由 lifespan 通过 AppContext 创建并管理生命周期。"""

    def __init__(self, apikey_service: APIKeyService, message_center: MessageCenter | None = None):
        self._domain = get_domain() or ""
        self.messagecenter = message_center or MessageCenter()
        self._client_manager = ClientManager(apikey_service=apikey_service, message=self)
        self._command_manager = CommandManager(self._client_manager)
        self._template_engine = TemplateEngine()
        self._dispatcher = MessageDispatcher(self._client_manager, self.messagecenter, self._domain)
        self._builder = MessageBuilder(
            self._client_manager,
            self._dispatcher,
            self.messagecenter,
            self._template_engine,
        )
        # 插件注册的消息命令
        self._command_manager._plugin_commands = {}

    def set_agent_enhancer(self, enhancer) -> None:
        """注入 Agent 通知增强器（单流替换模板；facade 与 builder 同步指向包装器）"""
        if enhancer is None:
            return

        wrapped = AgentEnhancingDispatcher(self._dispatcher, enhancer)
        self._dispatcher = wrapped
        self._builder._dispatcher = wrapped  # type: ignore[assignment] - 包装器行为兼容

    # ---------- 属性代理 ----------

    @property
    def active_clients(self):
        return self._client_manager.active_clients

    @property
    def active_interactive_clients(self):
        return self._client_manager.active_interactive_clients

    # ---------- 客户端管理委托 ----------

    def get_message_client_info(self, cid: Any = None) -> Any:
        return self._client_manager.get_message_client_info(cid)

    def get_interactive_client(self, client_type: Any = None) -> Any:
        return self._client_manager.get_interactive_client(client_type)

    def delete_message_client(self, cid: Any) -> Any:
        return self._client_manager.delete_message_client(cid)

    def update_message_client(self, cid: int, **kwargs) -> bool:
        return self._client_manager.update_message_client(cid=cid, **kwargs)

    def check_message_client(
        self, cid: Any = None, interactive: Any = None, enabled: Any = None, ctype: Any = None
    ) -> Any:
        return self._client_manager.check_message_client(cid, interactive, enabled, ctype)

    def insert_message_client(
        self,
        name: str,
        ctype: Any,
        config: str,
        switches: list,
        interactive: Any,
        enabled: Any,
        note: str = "",
        templates: Any = None,
    ) -> bool:
        return self._client_manager.insert_message_client(
            name, ctype, config, switches, interactive, enabled, note, templates
        )

    def reload_by_type(self, ctype: str) -> None:
        return self._client_manager.reload_by_type(ctype)

    def get_status(self, ctype: Any = None, config: Any = None) -> bool:
        return self._client_manager.get_status(ctype, config)

    # ---------- 命令管理委托 ----------

    def register_command(self, cmd: str, desc: str, func: Any, plugin_id: str = "") -> None:
        self._command_manager.register_command(cmd, desc, func, plugin_id)

    def unregister_command(self, cmd: str) -> None:
        self._command_manager.unregister_command(cmd)

    def clear_plugin_commands(self, plugin_id: str) -> None:
        self._command_manager.clear_plugin_commands(plugin_id)

    def get_commands(self) -> dict:
        return self._command_manager.get_commands()

    def get_plugin_commands(self) -> dict:
        return self._command_manager.get_plugin_commands()

    def refresh_menus(self) -> None:
        self._command_manager.refresh_menus()

    # ---------- 核心发送（保留在 Facade 以兼容外部直接调用） ----------

    def _do_sendmsg(self, client, title, text, image, url, user_id):
        return self._dispatcher._do_sendmsg(client, title, text, image, url, user_id)

    def send_channel_msg(
        self,
        channel: Any,
        title: str,
        text: str = "",
        image: str | None = None,
        url: str | None = None,
        user_id: str = "",
    ) -> bool:
        return self._dispatcher.send_channel_msg(channel, title, text, image, url, user_id)

    def send_channel_list_msg(self, channel: Any, title: str, medias: list, user_id: str = "") -> bool:
        return self._dispatcher.send_channel_list_msg(channel, title, medias, user_id)

    # ---------- 业务消息构建委托 ----------

    def send_download_message(self, in_from, can_item, download_setting_name=None, downloader_name=None) -> None:
        self._builder.send_download_message(in_from, can_item, download_setting_name, downloader_name)

    def send_transfer_movie_message(self, in_from, media_info, exist_filenum, category_flag) -> None:
        self._builder.send_transfer_movie_message(in_from, media_info, exist_filenum, category_flag)

    def send_transfer_tv_message(self, message_medias: dict, in_from, exist_filenum=0, category_flag=False) -> None:
        self._builder.send_transfer_tv_message(message_medias, in_from, exist_filenum, category_flag)

    def send_download_fail_message(self, item, error_msg: str) -> None:
        self._builder.send_download_fail_message(item, error_msg)

    def send_subscribe_success_message(self, in_from, media_info) -> None:
        self._builder.send_subscribe_success_message(in_from, media_info)

    def send_rss_finished_message(self, media_info) -> None:
        self._builder.send_rss_finished_message(media_info)

    def send_site_signin_message(self, msgs: list) -> None:
        self._builder.send_site_signin_message(msgs)

    def send_site_message(self, title=None, text=None) -> None:
        self._builder.send_site_message(title, text)

    def send_site_parse_health_message(self, title=None, text=None) -> None:
        self._builder.send_site_parse_health_message(title, text)

    def send_transfer_fail_message(self, path: str, count: int, text: str) -> None:
        self._builder.send_transfer_fail_message(path, count, text)

    def send_auto_remove_torrents_message(self, title: str, text: str) -> None:
        self._builder.send_auto_remove_torrents_message(title, text)

    def send_brushtask_remove_message(self, title: str, text: str) -> None:
        self._builder.send_brushtask_remove_message(title, text)

    def send_brushtask_added_message(self, title: str, text: str) -> None:
        self._builder.send_brushtask_added_message(title, text)

    def send_brushtask_pause_message(self, title: str, text: str) -> None:
        self._builder.send_brushtask_pause_message(title, text)

    def send_mediaserver_message(self, event_info: dict, channel: Any, image_url: str | None) -> None:
        self._builder.send_mediaserver_message(event_info, channel, image_url)

    def send_plugin_message(
        self, title: str, text: str | None = "", image: str | None = "", url: str | None = ""
    ) -> None:
        self._builder.send_plugin_message(title, text, image, url)

    def send_custom_message(self, clients: Any, title: str, text: str = "", image: str = "") -> None:
        self._builder.send_custom_message(clients, title, text, image)

    def send_user_statistics_message(self, msgs: list) -> None:
        self._builder.send_user_statistics_message(msgs)

    # ---------- 其他委托 ----------

    def get_search_types(self) -> list:
        return self._dispatcher.get_search_types()
