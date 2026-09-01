"""存储后端工厂 — 注册表模式。"""

from typing import Any, ClassVar

from app.storage.backends.base import StorageBackend, StorageConfig, StorageType
from app.storage.backends.local import LocalStorageBackend
from app.storage.backends.openlist import OpenListStorageBackend
from app.storage.backends.rclone import RcloneStorageBackend
from app.storage.backends.s3 import S3StorageBackend
from app.storage.backends.smb import SMBStorageBackend
from app.storage.backends.webdav import WebDAVStorageBackend
from app.storage.config_models import (
    LocalStorageConfig,
    OpenListStorageConfig,
    RcloneStorageConfig,
    S3StorageConfig,
    SMBStorageConfig,
    WebDAVStorageConfig,
)


class StorageBackendFactory:
    """存储后端工厂，同时管理后端类与配置类的注册。"""

    _registry: ClassVar[dict[StorageType | str, type[StorageBackend]]] = {}
    _config_registry: ClassVar[dict[str, tuple[StorageType | str, type[StorageConfig], list[dict], str]]] = {}

    @classmethod
    def register(
        cls,
        stype: StorageType | str,
        backend_cls: type[StorageBackend],
        config_cls: type[StorageConfig] | None = None,
        type_key: str | None = None,
        icon: str = "lucide:hard-drive",
    ) -> None:
        """
        注册存储后端。

        :param stype: StorageType 枚举值或插件自定义字符串标识（如 "plugin_backend"）
        :param backend_cls: StorageBackend 实现类
        :param config_cls: 对应的 StorageConfig 子类（可选）
        :param type_key: 数据库/配置中使用的类型字符串（如 "s3" "alist"）
        :param icon: 前端图标标识
        """
        cls._registry[stype] = backend_cls
        if type_key and config_cls:
            fields = config_cls.get_fields() if hasattr(config_cls, "get_fields") else []
            cls._config_registry[type_key] = (stype, config_cls, fields, icon)

    @classmethod
    def unregister(cls, stype: StorageType | str, type_key: str | None = None) -> None:
        """注销存储后端（插件禁用时调用）"""
        cls._registry.pop(stype, None)
        if type_key:
            cls._config_registry.pop(type_key, None)

    @classmethod
    def get_type_schema(cls) -> list[dict]:
        """获取所有注册类型的完整 schema（含字段定义和图标）。"""
        result = []
        for type_key, (stype, _config_cls, fields, icon) in cls._config_registry.items():
            label = stype.name if isinstance(stype, StorageType) else stype
            result.append(
                {
                    "key": type_key,
                    "label": label,
                    "fields": fields,
                    "icon": icon,
                }
            )
        return result

    @classmethod
    def get_config_info(cls, type_key: str) -> tuple[Any, type[StorageConfig]] | None:
        """根据类型字符串获取 (StorageType, ConfigClass)。"""
        info = cls._config_registry.get(type_key)
        if info:
            return info[0], info[1]
        return None

    @classmethod
    def get_type_icon(cls, type_key: str) -> str:
        """获取指定类型的图标标识。"""
        info = cls._config_registry.get(type_key)
        return info[3] if info else "lucide:hard-drive"

    @classmethod
    def create(cls, config: StorageConfig) -> StorageBackend:
        backend_cls = cls._registry.get(config.type)
        if not backend_cls:
            raise ValueError(f"不支持的存储类型: {config.type}")
        return backend_cls(config)

    @classmethod
    def list_supported_types(cls) -> list[StorageType | str]:
        return list(cls._registry.keys())

    @classmethod
    def list_registered_type_keys(cls) -> list[str]:
        return list(cls._config_registry.keys())


# 注册内置后端
StorageBackendFactory.register(
    StorageType.LOCAL, LocalStorageBackend, config_cls=LocalStorageConfig, type_key="local", icon="lucide:hard-drive"
)
StorageBackendFactory.register(
    StorageType.WEBDAV, WebDAVStorageBackend, config_cls=WebDAVStorageConfig, type_key="webdav", icon="lucide:globe"
)
StorageBackendFactory.register(
    StorageType.SMB, SMBStorageBackend, config_cls=SMBStorageConfig, type_key="smb", icon="lucide:network"
)
StorageBackendFactory.register(
    StorageType.S3, S3StorageBackend, config_cls=S3StorageConfig, type_key="s3", icon="lucide:cloud"
)
StorageBackendFactory.register(
    StorageType.RCLONE,
    RcloneStorageBackend,
    config_cls=RcloneStorageConfig,
    type_key="rclone",
    icon="lucide:arrow-left-right",
)
StorageBackendFactory.register(
    StorageType.OPENLIST,
    OpenListStorageBackend,
    config_cls=OpenListStorageConfig,
    type_key="openlist",
    icon="lucide:list",
)
