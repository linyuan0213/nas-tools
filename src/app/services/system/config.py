"""Config services - 索引器、媒体服务器、系统配置与配置更新."""

import json
from typing import cast

from sqlalchemy import text

import log
from app.core.exceptions import DomainError, RepositoryError, ServiceError
from app.core.settings import settings
from app.core.system_config import SystemConfig
from app.db.repositories.base_repository import BaseRepository
from app.db.repositories.config_repo_adapter import MediaServerRepositoryAdapter
from app.db.repositories.indexer_config_repo_adapter import IndexerConfigRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.domain.enums import SystemConfigKey
from app.indexer.indexer import Indexer
from app.indexer.registry import get_all_clients
from app.infrastructure.cache_system import TokenCache
from app.mediaserver import MediaServer
from app.mediaserver.registry import get_all_clients as get_all_mediaserver_clients
from app.schemas.system import (
    ConfigUpdateResultDTO,
    IndexerConfigResultDTO,
    MediaServerConfigResultDTO,
)
from app.services.indexer_service import IndexerService
from app.services.web.utils import set_config_value
from app.utils import ExceptionUtils
from app.utils.json_utils import JsonUtils
from app.utils.submodule_loader import SubmoduleLoader


class IndexerConfigService:
    """
    索引器配置业务服务
    使用 INDEXER_CONFIG 表持久化各索引器客户端的配置和启用状态。
    首次读取时自动从旧 SystemConfig 迁移已有配置。
    """

    def __init__(
        self,
        indexer_service: IndexerService,
        indexer: Indexer,
        system_config: SystemConfig | None = None,
        site_config_repo: IndexerSiteConfigRepositoryAdapter | None = None,
        idx_config_repo: IndexerConfigRepositoryAdapter | None = None,
    ):
        self._system_config = system_config or SystemConfig()
        self._indexer_service = indexer_service
        self._indexer = indexer
        self._site_config_repo = site_config_repo or IndexerSiteConfigRepositoryAdapter()
        self._idx_config_repo = idx_config_repo or IndexerConfigRepositoryAdapter()

    def _migrate_from_legacy(self, client_id: str) -> dict | None:
        """从旧 SystemConfig 读取配置并迁移到新表"""
        old_all = self._system_config.get(SystemConfigKey.IndexerConfig) or {}
        old_cfg = old_all.get(client_id) or {}

        old_enabled_str = None
        if client_id == "builtin":
            old_enabled_str = self._system_config.get(SystemConfigKey.BuiltinIndexerEnabled)
        elif client_id == "jackett":
            old_enabled_str = self._system_config.get(SystemConfigKey.JackettIndexerEnabled)
        elif client_id == "prowlarr":
            old_enabled_str = self._system_config.get(SystemConfigKey.ProwlarrIndexerEnabled)

        old_enabled = True if old_enabled_str is None else str(old_enabled_str) != "0"

        if not old_cfg and client_id != "builtin":
            yml_cfg = settings.get(client_id)
            if yml_cfg:
                old_cfg = dict(yml_cfg)

        if not old_cfg and old_enabled_str is None and client_id != "builtin":
            return None

        self._idx_config_repo.upsert(client_id=client_id, enabled=old_enabled, config=old_cfg)
        return old_cfg

    def get_all_configs(self) -> list:
        # 自动从旧 SystemConfig 迁移历史数据
        for cid in ("builtin", "jackett", "prowlarr"):
            if self._idx_config_repo.get_by_client_id(cid) is None:
                self._migrate_from_legacy(cid)

        entities = self._idx_config_repo.get_all()
        result = []
        for e in entities:
            if e.config:
                self._fill_config_keys(e.client_id, e.config)
            result.append({"client_id": e.client_id, "enabled": e.enabled, "config": e.config})
        return result

    def get_config(self, client_id: str) -> dict | None:
        entity = self._idx_config_repo.get_by_client_id(client_id)
        if entity is not None:
            return {"client_id": entity.client_id, "enabled": entity.enabled, "config": entity.config}
        return self._migrate_from_legacy(client_id)

    def is_enabled(self, client_id: str) -> bool:
        entity = self._idx_config_repo.get_by_client_id(client_id)
        if entity is not None:
            return entity.enabled
        row = self._migrate_from_legacy(client_id)
        if row is not None:
            return row.get("enabled", True)
        return client_id == "builtin"

    def _fill_config_keys(self, client_id: str, config: dict) -> None:
        """填充配置字典的 key 为 config schema 中定义的字段 id"""

        for cls in get_all_clients():
            if hasattr(cls, "client_id") and cls.client_id == client_id:
                if hasattr(cls, "config_schema") and cls.config_schema:
                    for field in cls.config_schema.fields:
                        if field.id not in config:
                            config[field.id] = ""

    def save_config(self, data: dict) -> IndexerConfigResultDTO:
        """保存索引器配置"""
        name = data.get("type") or ""
        test = data.get("test") in [True, "true", "on", "1", 1]
        enabled = data.get("enabled")

        # 先确保旧配置已迁移
        existing = self.get_config(name) or {}
        old_config = existing.get("config", {})

        # 提取新配置
        config = dict(old_config)
        for key, value in data.items():
            if key.startswith(name + "."):
                config[key.split(".", 1)[1]] = value
            elif key not in ("type", "test", "set_default_indexer", "enabled"):
                config[key] = value

        self._idx_config_repo.upsert(
            client_id=name,
            enabled=enabled,
            config=config,
        )

        # 刷新 Indexer 单例配置
        self._indexer._refresh()

        # 同步第三方索引器站点列表
        if name != "builtin":
            self._sync_third_party_sites(name, config)

        # 测试连接
        if test and name != "builtin":
            try:
                schemas = SubmoduleLoader.import_submodules(
                    "app.indexer.client", filter_func=lambda _, obj: hasattr(obj, "client_id")
                )
                for schema in schemas:
                    if schema.client_id == name and hasattr(schema, "match") and schema.match(name):
                        indexer = schema(config=config)
                        ok = indexer.get_status()
                        return IndexerConfigResultDTO(
                            success=True, msg="连接成功" if ok else "连接失败", code=0 if ok else 1
                        )
                return IndexerConfigResultDTO(success=False, msg="未找到对应的索引器客户端", code=1)
            except Exception as e:
                return IndexerConfigResultDTO(success=False, msg=str(e), code=1)

        return IndexerConfigResultDTO(success=True, msg="保存成功", code=0)

    def _sync_third_party_sites(self, client_type: str, config: dict) -> None:
        """同步第三方索引器的站点列表到 INDEXER_SITE_CONFIG 表"""
        if not config.get("host") or not config.get("api_key"):
            return
        try:
            schemas = SubmoduleLoader.import_submodules(
                "app.indexer.client", filter_func=lambda _, obj: hasattr(obj, "client_id")
            )
            for schema in schemas:
                if schema.client_id == client_type and hasattr(schema, "match") and schema.match(client_type):
                    client = schema(config=config)
                    indexers = client.get_indexers(check=False)
                    if indexers:
                        for idx in indexers:
                            self._site_config_repo.upsert_site(
                                site_name=idx.name,
                                source=client_type,
                                public=bool(getattr(idx, "public", False)),
                            )
                    break
        except Exception as e:
            log.warn(f"[IndexerConfigService]同步{client_type}站点列表失败: {e}")


class MediaServerConfigService:
    """
    媒体服务器配置业务服务
    负责保存媒体服务器配置、测试连接
    """

    def __init__(self, media_server: MediaServer, config_repo=None):

        self._config_repo = config_repo or MediaServerRepositoryAdapter()
        self._media_server = media_server

    def get_media_servers_info(self) -> dict:
        """获取媒体服务器配置信息（包含服务器列表、默认服务器名称）"""
        servers = self._config_repo.get_media_servers()
        default_server = self._config_repo.get_default_media_server()
        server_dict = {}
        for item in servers:
            try:
                cfg = JsonUtils.loads(str(item.CONFIG)) if str(item.CONFIG or "") else {}
            except json.JSONDecodeError:
                cfg = {}
            server_dict[item.NAME] = {
                "id": item.ID,
                "name": item.NAME,
                "enabled": item.ENABLED,
                "is_default": item.IS_DEFAULT,
                "config": cfg,
            }
        return {
            "servers": server_dict,
            "default_server": default_server.NAME if default_server else None,
        }

    def save_config(self, data: dict) -> MediaServerConfigResultDTO:
        """保存媒体服务器配置"""
        name = data.get("type") or ""
        test = data.get("test") in [True, "true", "on", "1", 1]
        config = {}
        for key, value in data.items():
            if key.startswith(name + "."):
                config[key.split(".", 1)[1]] = value
            elif key not in ("type", "test"):
                config[key] = value
        if not config:
            return MediaServerConfigResultDTO(success=False, code=-1, msg="配置为空")
        enabled = 1 if config.get("enabled") else 0
        is_default = 1 if config.get("is_default") else 0
        item = self._config_repo.get_media_server_by_name(name)
        sid = cast(int, item.ID) if item else None
        self._config_repo.update_media_server(
            sid=int(sid) if sid else None,
            name=name,
            enabled=enabled,
            config=JsonUtils.dumps(config),
            is_default=is_default,
        )
        if is_default:
            self._config_repo.set_default_media_server(name)
        self._media_server._refresh()
        TokenCache.delete("index")
        if test:
            try:
                # 遍历注册表（含插件注册的媒体服务器客户端），而非仅扫描内置目录
                for schema in get_all_mediaserver_clients():
                    if schema.match(name):
                        client = schema(config)
                        status = client.get_status()
                        return MediaServerConfigResultDTO(
                            success=True, code=0 if status else 1, msg="测试成功" if status else "测试失败"
                        )
                return MediaServerConfigResultDTO(success=False, code=-1, msg="未找到对应客户端")
            except (ServiceError, RepositoryError, DomainError):
                raise
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                return MediaServerConfigResultDTO(success=False, code=-1, msg=str(e))
        return MediaServerConfigResultDTO(success=True)

    def apply_config(
        self,
        name: str,
        config_overlay: dict | None = None,
        enabled: bool | None = None,
        is_default: bool | None = None,
    ) -> None:
        """统一媒体服务器新增/更新入口：合并现有配置后经 save_config 落库，供 Agent 工具与 manifest 复用.

        enabled/is_default 为三态：None=保留现状；失败抛 ValueError（含“媒体服务器不存在”等提示）。
        """
        info = self.get_media_servers_info()
        current = (info.get("servers") or {}).get(name) or {}
        if not current:
            raise ValueError(f"媒体服务器不存在: {name}")
        merged = dict(current.get("config") or {})
        if enabled is not None:
            merged["enabled"] = 1 if enabled else 0
        if is_default is not None:
            merged["is_default"] = 1 if is_default else 0
        merged.update({k: v for k, v in (config_overlay or {}).items() if v is not None})
        result = self.save_config({"type": name, **merged})
        if not getattr(result, "success", True):
            raise ValueError(getattr(result, "msg", "保存失败"))


class SystemConfigService:
    """
    系统配置业务服务
    """

    def __init__(self, system_config: SystemConfig | None = None):
        self._system_config = system_config or SystemConfig()

    def get(self, key=None):
        """获取系统配置项"""
        return self._system_config.get(key)

    def set(self, key: str, value) -> None:
        """设置系统配置项"""
        self._system_config.set(key=key, value=value)

    def set_config(self, key: str, value) -> bool:
        """设置系统配置项（兼容旧接口）"""
        if not key or not value:
            return False
        self._system_config.set(key=key, value=value)
        return True

    def reset_db_version(self) -> None:
        """重置数据库 alembic_version 表（用于版本回滚后重建）"""
        with BaseRepository().session() as db:
            db.execute(text("DROP TABLE IF EXISTS alembic_version"))


class ConfigUpdateService:
    """
    配置更新业务服务（文件配置 + 数据库配置合并更新）
    """

    @staticmethod
    def update_config(data: dict) -> ConfigUpdateResultDTO:
        cfg = settings.get()
        config_test = False
        for key, value in dict(data).items():
            if key == "test" and value:
                config_test = True
                continue
            cfg = set_config_value(cfg, key, value)
        if not config_test:
            cfg.pop("test", None)
            settings.save(cfg)
            settings.reload()
        return ConfigUpdateResultDTO(success=True, test_mode=config_test)
