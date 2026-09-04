"""Message services - 消息客户端、发送与命令处理."""

import json
from typing import cast

from app.domain.enums import SearchType, channel_name
from app.events import Event
from app.events.constants import MESSAGE_INCOMING
from app.events.payloads import MessageIncomingPayload
from app.infrastructure.cache_system import TokenCache, get_cache_manager
from app.message import Message
from app.message.commands import COMMANDS
from app.schemas.system import SendMessageResultDTO
from app.services.rbac.init.constants import DEFAULT_PERMISSIONS
from app.utils.json_utils import JsonUtils

# webhook/IM 交互渠道经 apikey+IP 白名单认证后视为全权渠道：
# 不再以 user_permissions=None 跳过 RBAC（fail-open），而是显式授予全部权限码，
# 让工具/命令的权限校验始终生效（后续可在入口处按渠道收紧）。
_TRUSTED_CHANNEL_PERMISSIONS = [p["code"] for p in DEFAULT_PERMISSIONS]


class MessageClientService:
    """
    消息客户端业务服务
    负责消息客户端的增删改查、交互状态管理、连接测试
    """

    def __init__(self, message: Message):
        self._message = message

    def delete_client(self, cid: int) -> bool:
        """删除消息客户端"""
        return bool(self._message.delete_message_client(cid=cid))

    def get_client(self, cid: int | None = None):
        """获取消息客户端信息"""
        return self._message.get_message_client_info(cid=cid)

    def toggle_interactive(self, cid: int, ctype: str, checked: bool) -> bool:
        """切换交互状态"""
        if checked:
            self._message.check_message_client(interactive=0, ctype=ctype)
        self._message.check_message_client(cid=cid, interactive=1 if checked else 0)
        return True

    def toggle_enable(self, cid: int, checked: bool) -> bool:
        """切换启用状态"""
        self._message.check_message_client(cid=cid, enabled=1 if checked else 0)
        return True

    def test_connection(self, ctype: str, config: dict) -> bool:
        """测试消息客户端连接"""
        return self._message.get_status(ctype=ctype, config=config)

    def upsert_client(
        self, name: str, cid: int, ctype: str, config: str, switches, interactive: int, enabled: int, templates: str
    ) -> None:
        """添加或更新消息客户端"""
        parsed_switches = switches
        if isinstance(switches, str):
            try:
                parsed_switches = JsonUtils.loads(switches)
                if not isinstance(parsed_switches, list):
                    parsed_switches = []
            except json.JSONDecodeError:
                parsed_switches = [s.strip() for s in switches.split(",") if s.strip()]
        if not isinstance(parsed_switches, list):
            parsed_switches = []
        if int(interactive) == 1:
            self._message.check_message_client(interactive=0, ctype=ctype)
        if cid:
            self._message.update_message_client(
                cid=cid,
                name=name,
                ctype=ctype,
                config=config,
                switches=parsed_switches,
                interactive=interactive,
                enabled=enabled,
                templates=templates,
            )
        else:
            self._message.insert_message_client(
                name=name,
                ctype=ctype,
                config=config,
                switches=parsed_switches,
                interactive=interactive,
                enabled=enabled,
                templates=templates,
            )


class MessageSenderService:
    """
    消息发送业务服务
    """

    def __init__(self, message: Message):
        self._message = message

    def send_custom_message(self, clients: list, title: str, text: str, image: str = "") -> SendMessageResultDTO:
        if not clients:
            return SendMessageResultDTO(success=False, message="未选择消息服务")
        self._message.send_custom_message(clients=clients, title=title, text=text, image=image)
        return SendMessageResultDTO(success=True)

    def send_plugin_message(self, title: str, text: str, image: str = "") -> SendMessageResultDTO:
        self._message.send_plugin_message(title=title, text=text, image=image)
        return SendMessageResultDTO(success=True)


class MessageCommandHandler:
    """
    消息命令处理器
    """

    def __init__(
        self,
        search_handler=None,
        torrent_remover_service=None,
        downloader_core=None,
        sync_service=None,
        filetransfer_service=None,
        event_bus=None,
        thread_executor=None,
        message=None,
        subscription_monitor=None,
        rss_task_service=None,
        subscribe_service=None,
        site_service=None,
        system_lifecycle=None,
    ):
        self._search_handler = search_handler
        self._torrent_remover_service = torrent_remover_service
        self._downloader_core = downloader_core
        self._sync_service = sync_service
        self._filetransfer_service = filetransfer_service
        self._event_bus = event_bus
        self._thread_executor = thread_executor
        self._message = message
        self._subscription_monitor = subscription_monitor
        self._rss_task_service = rss_task_service
        self._subscribe_service = subscribe_service
        self._site_service = site_service
        self._system_lifecycle = system_lifecycle
        self._commands = None

    @staticmethod
    def _func(service, method):
        """依赖缺失时返回空操作，避免菜单点击报错"""
        return getattr(service, method) if service else (lambda: None)

    @property
    def _command_map(self):
        if self._commands is None:
            self._commands = {
                "/ptr": {
                    "func": self._func(self._torrent_remover_service, "auto_remove_torrents"),
                    "desc": COMMANDS["/ptr"],
                },
                "/ptt": {
                    "func": self._func(self._downloader_core, "transfer"),
                    "desc": COMMANDS["/ptt"],
                },
                "/rst": {
                    "func": self._func(self._sync_service, "transfer_sync"),
                    "desc": COMMANDS["/rst"],
                },
                "/sub": {
                    "func": self._func(self._subscription_monitor, "run"),
                    "desc": COMMANDS.get("/sub", "订阅监控"),
                },
                "/clr": {
                    "func": self._clear_caches,
                    "desc": COMMANDS["/clr"],
                },
                "/utf": {
                    "func": self._unidentification,
                    "desc": COMMANDS["/utf"],
                },
                "/udt": {
                    "func": self._func(self._system_lifecycle, "restart_server"),
                    "desc": COMMANDS["/udt"],
                },
                "/sta": {
                    "func": self._user_statistics,
                    "desc": COMMANDS["/sta"],
                },
            }
        return self._commands

    _SEARCH_COMMAND_PREFIXES = ("/rss", "/ssa", "订阅", "搜索", "下载")

    # 管理类命令所需权限（Web 内置消息页按用户权限执行；webhook/IM 渠道在入口处
    # 显式授予全权限后同样经此处校验，避免“不传权限即放行”的旁路）
    _COMMAND_PERMISSIONS: dict[str, str] = {
        "/udt": "setting:update",
        "/clr": "setting:update",
        "/ptt": "setting:update",
        "/rst": "setting:update",
        "/ptr": "setting:update",
        "/sub": "setting:update",
        "/utf": "setting:update",
    }

    def _check_command_permission(self, command: str, user_permissions: list[str] | None) -> bool:
        """命令权限校验：user_permissions 由调用方显式传入（web=用户权限，webhook/IM=全权限）"""
        if user_permissions is None:
            return True
        required = self._COMMAND_PERMISSIONS.get(command)
        if required and required not in user_permissions:
            return False
        return True

    def _is_search_command(self, msg: str) -> bool:
        """判断是否为搜索/订阅类命令前缀（支持斜杠命令和中文命令）."""
        return any(msg.startswith(prefix) for prefix in self._SEARCH_COMMAND_PREFIXES)

    def _check_search_permission(self, msg: str, user_permissions: list[str] | None) -> bool:
        """自由文本搜索意图权限：下载/URL/magnet 需 download:manage，订阅需 subscription:manage"""
        if user_permissions is None:
            return True
        lower = msg.lower()
        if any(k in lower for k in ("magnet:", "http://", "https://")) or "下载" in msg:
            if "download:manage" not in user_permissions:
                return False
        if "订阅" in msg and "subscription:manage" not in user_permissions:
            return False
        return True

    def handle_message_job(
        self, msg, in_from: SearchType | str = SearchType.OT, user_id=None, user_name=None, user_permissions=None
    ):
        """处理消息事件（user_permissions: Web 用户权限列表，None=webhook/IM 渠道）"""
        if not msg:
            return

        # webhook/IM 渠道：显式授予全权限（取代旧的“None=跳过校验”），保证 RBAC 始终生效
        permissions = user_permissions if user_permissions is not None else list(_TRUSTED_CHANNEL_PERMISSIONS)

        if self._event_bus:
            self._event_bus.publish(
                Event(
                    event_type=MESSAGE_INCOMING,
                    payload=MessageIncomingPayload(
                        channel=channel_name(in_from), user_id=user_id, user_name=user_name, message=msg
                    ),
                )
            )

        # 搜索/订阅类命令（含中文"订阅"、"搜索"、"下载"及 /rss、/ssa）直接交给搜索服务
        if self._is_search_command(msg):
            if not self._check_search_permission(msg, permissions):
                if self._message:
                    self._message.send_channel_msg(
                        channel=in_from, title="权限不足，无法执行该操作", user_id=user_id or ""
                    )
                return
            if self._message:
                self._message.send_channel_msg(channel=in_from, title="正在搜索/订阅，请稍候...", user_id=user_id or "")
            TokenCache.delete("search")
            if self._search_handler and self._thread_executor:
                self._thread_executor.submit(self._search_handler.handle, msg, in_from, user_id, user_name, permissions)
            return

        command = self._command_map.get(msg)
        if command:
            if not self._check_command_permission(msg, permissions):
                if self._message:
                    self._message.send_channel_msg(
                        channel=in_from,
                        title=f"权限不足，无法执行 {command.get('desc')}",
                        user_id=user_id or "",
                    )
                return
            if func := command.get("func"):
                if self._thread_executor:
                    self._thread_executor.submit(func)
            if self._message:
                self._message.send_channel_msg(
                    channel=in_from, title="正在运行 {} ...".format(command.get("desc")), user_id=user_id or ""
                )
            return

        # 插件命令
        if self._message:
            plugin_commands = self._message.get_plugin_commands()
            msg_list = msg.split(" ")
            cmd_key = msg_list[0]
            plugin_cmd = plugin_commands.get(cmd_key)
            if plugin_cmd:
                func = plugin_cmd.get("func")
                if func and self._thread_executor:
                    self._thread_executor.submit(func, msg, in_from, user_id, user_name)
                self._message.send_channel_msg(
                    channel=in_from, title="正在运行 {} ...".format(plugin_cmd.get("desc")), user_id=user_id or ""
                )
                return

        TokenCache.delete("search")
        if self._search_handler and self._thread_executor:
            self._thread_executor.submit(self._search_handler.handle, msg, in_from, user_id, user_name, permissions)
            if self._message:
                self._message.send_channel_msg(channel=in_from, title="正在处理，请稍候...", user_id=user_id or "")

    def _truncate_rsshistory(self):
        rsshelper = getattr(self._rss_task_service, "rsshelper", None)
        if rsshelper:
            rsshelper.truncate_rss_history()
        if self._subscribe_service:
            self._subscribe_service.truncate_rss_episodes()

    def _clear_caches(self):
        """清理缓存系统全部缓存（Redis/内存）"""
        get_cache_manager().clear_all()

    def _user_statistics(self):
        TokenCache.delete("statistics")
        if self._site_service:
            self._site_service.refresh_site_data_now()

    def _unidentification(self):
        if not self._filetransfer_service:
            return
        records = self._filetransfer_service.get_transfer_unknown_paths()
        if not records:
            return
        item_ids = []
        for rec in records:
            if not cast(str, rec.PATH):
                continue
            item_ids.append(rec.ID)
        if len(item_ids) > 0 and self._sync_service:
            self._sync_service.re_identify_items(flag="unidentification", ids=item_ids)
