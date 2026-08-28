"""ClientManager - 消息客户端生命周期管理."""

import json
from enum import Enum
from typing import Any, cast

import log
from app.db.repositories.config_repo_adapter import MessageClientRepositoryAdapter
from app.infrastructure.thread import ThreadExecutor
from app.message.client_registry import ClientRegistry
from app.message.registry import get_client_class
from app.message.switches import MESSAGE_SWITCHES
from app.services.apikey_service import APIKeyService
from app.utils.json_utils import JsonUtils


def parse_client_config(client_config) -> dict:
    """解析数据库中的客户端配置为结构化字典."""

    config = {}
    if client_config.CONFIG:
        try:
            config = JsonUtils.loads(client_config.CONFIG)
        except json.JSONDecodeError:
            log.error(f"[Message]客户端 {client_config.NAME} 的 CONFIG 不是有效 JSON: {client_config.CONFIG}")
    config.update({"interactive": client_config.INTERACTIVE})
    templates = {}
    if client_config.TEMPLATES:
        try:
            templates = JsonUtils.loads(client_config.TEMPLATES)
        except json.JSONDecodeError:
            log.error(f"[Message]客户端 {client_config.NAME} 的模板配置不是有效的 JSON: {client_config.TEMPLATES}")
    switches = []
    if client_config.SWITCHES:
        try:
            parsed = JsonUtils.loads(client_config.SWITCHES)
            if isinstance(parsed, list):
                switches = parsed
            elif isinstance(parsed, str):
                all_keys = set(MESSAGE_SWITCHES.keys())
                switches = [s.strip() for s in parsed.split(",") if s.strip() and s.strip() in all_keys]
        except json.JSONDecodeError:
            raw = str(client_config.SWITCHES)
            all_keys = set(MESSAGE_SWITCHES.keys())
            switches = [s.strip() for s in raw.split(",") if s.strip() and s.strip() in all_keys]
    return {
        "id": client_config.ID,
        "name": client_config.NAME,
        "type": client_config.TYPE,
        "config": config,
        "switches": switches,
        "interactive": client_config.INTERACTIVE,
        "enabled": client_config.ENABLED,
        "templates": templates,
    }


class ClientManager:
    """负责消息客户端的加载、刷新、移除和查询."""

    def __init__(self, apikey_service: APIKeyService | None = None, config_repo=None, message=None):
        self.config_repo = config_repo or MessageClientRepositoryAdapter()
        self._apikey_service = apikey_service
        self._message = message
        self._active_clients: list = []
        self._active_interactive_clients: dict = {}
        self._client_configs: dict = {}

    @property
    def active_clients(self):
        self._ensure_loaded()
        return self._active_clients

    @property
    def active_interactive_clients(self):
        self._ensure_loaded()
        return self._active_interactive_clients

    def _ensure_loaded(self):
        if not self.config_repo:
            return
        db_clients = {str(c.ID): c for c in self.config_repo.get_message_client() or []}

        # Remove clients that no longer exist in DB or are disabled/empty
        for cid in list(self._client_configs.keys()):
            if cid not in db_clients:
                self._remove_client(cid)
                continue
            client_config = db_clients[cid]
            if not (cast(bool, client_config.ENABLED) and str(client_config.CONFIG)):
                self._remove_client(cid)

        # Add new clients or refresh existing ones when interactive/enabled changed
        for cid, client_config in db_clients.items():
            if not (cast(bool, client_config.ENABLED) and str(client_config.CONFIG)):
                continue
            old_config = self._client_configs.get(cid)
            if old_config is None:
                self._add_client_from_config(client_config)
            elif old_config.get("interactive") != bool(client_config.INTERACTIVE) or old_config.get("enabled") != bool(
                client_config.ENABLED
            ):
                self._add_client_from_config(client_config)

    def _add_client_from_config(self, client_config):
        cid = str(client_config.ID)
        self._remove_client(cid)
        config = parse_client_config(client_config)
        self._client_configs[cid] = config
        client_entry = {
            "id": client_config.ID,
            "name": client_config.NAME,
            "type": client_config.TYPE,
            "config": config["config"],
            "switches": config["switches"],
            "interactive": client_config.INTERACTIVE,
            "enabled": client_config.ENABLED,
            "templates": config["templates"],
            "search_type": self._get_search_type(client_config.TYPE),
            "max_length": self._get_max_length(client_config.TYPE),
            "client": ClientRegistry.build(
                ctype=client_config.TYPE,
                conf=config["config"],
                apikey_service=self._apikey_service,
                message=self._message,
            ),
        }
        client_instance = client_entry["client"]
        if hasattr(client_instance, "setup"):
            ThreadExecutor(name="msg_setup").submit(client_instance.setup)
        self._active_clients.append(client_entry)
        if client_config.INTERACTIVE:
            self._active_interactive_clients[client_entry["search_type"]] = client_entry

    @staticmethod
    def _get_search_type(ctype: str) -> str | None:
        cls = get_client_class(ctype)
        if cls and hasattr(cls, "config_schema") and cls.config_schema:
            return cls.config_schema.search_type
        return None

    @staticmethod
    def _get_max_length(ctype: str) -> int | None:
        cls = get_client_class(ctype)
        if cls and hasattr(cls, "config_schema") and cls.config_schema:
            return cls.config_schema.max_length
        return None

    def _remove_client(self, cid):
        cid = str(cid)
        self._active_clients = [c for c in self._active_clients if str(c.get("id")) != cid]
        keys_to_remove = [k for k, v in self._active_interactive_clients.items() if str(v.get("id")) == cid]
        for k in keys_to_remove:
            del self._active_interactive_clients[k]
        if cid in self._client_configs:
            del self._client_configs[cid]

    def refresh_client(self, cid):
        self._ensure_loaded()
        client_config = self._get_client_config_by_id(cid)
        if not client_config:
            self._remove_client(cid)
            return
        if cast(bool, client_config.ENABLED) and str(client_config.CONFIG):
            self._add_client_from_config(client_config)
        else:
            self._remove_client(str(cid))
            self._client_configs[str(cid)] = parse_client_config(client_config)

    def _get_client_config_by_id(self, cid):
        if not self.config_repo:
            return None
        for config in self.config_repo.get_message_client() or []:
            if str(config.ID) == str(cid):
                return config
        return None

    def get_message_client_info(self, cid: Any = None) -> Any:
        self._ensure_loaded()
        if cid:
            return self._client_configs.get(str(cid))
        return self._client_configs

    def get_interactive_client(self, client_type: Any = None) -> Any:
        self._ensure_loaded()
        if not client_type:
            return list(self._active_interactive_clients.values())
        key = client_type.name if isinstance(client_type, Enum) else client_type
        return self._active_interactive_clients.get(key)

    def delete_message_client(self, cid: Any) -> Any:
        self._ensure_loaded()
        if not self.config_repo:
            return None
        ret = self.config_repo.delete_message_client(cid=cid)
        self._remove_client(cid)
        return ret

    def check_message_client(
        self, cid: Any = None, interactive: Any = None, enabled: Any = None, ctype: Any = None
    ) -> Any:
        self._ensure_loaded()
        if not self.config_repo:
            return None
        ret = self.config_repo.check_message_client(cid=cid, interactive=interactive, enabled=enabled, ctype=ctype)
        if cid:
            self.refresh_client(cid)
        if ctype:
            for c in list(self._active_clients):
                if c.get("type") == ctype:
                    self.refresh_client(c.get("id"))
        return ret

    def update_message_client(self, cid: int, **kwargs) -> bool:
        """更新消息客户端并刷新内存缓存."""
        self._ensure_loaded()
        if not self.config_repo:
            return False
        updated_id = self.config_repo.update_message_client(cid=cid, **kwargs)
        if updated_id:
            self.refresh_client(cid)
            return True
        return False

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
        """新增消息客户端."""
        self._ensure_loaded()
        if not self.config_repo:
            return False
        new_id = self.config_repo.insert_message_client(
            name=name,
            ctype=ctype,
            config=config,
            switches=switches,
            interactive=interactive,
            enabled=enabled,
            note=note,
            templates=templates,
        )
        self.refresh_client(new_id)
        return True

    def reload_by_type(self, ctype: str) -> None:
        self._ensure_loaded()
        if not self.config_repo:
            return
        for client_config in self.config_repo.get_message_client() or []:
            if client_config.TYPE == ctype and cast(bool, client_config.ENABLED):
                self.refresh_client(client_config.ID)
                break

    def get_status(self, ctype: Any = None, config: Any = None) -> bool:
        """测试消息设置状态."""
        if not ctype:
            return False
        built_client = ClientRegistry.build(
            ctype=ctype,
            conf=config or {},
            apikey_service=self._apikey_service,
            message=self._message,
        )
        if not built_client:
            return False
        state, ret_msg = built_client.send_msg(
            title="测试", text="这是一条测试消息", url="https://github.com/linyuan0213/nexus-media"
        )
        if not state:
            log.error(f"[Message]{ctype} 发送测试消息失败：%s" % ret_msg)
        return state
