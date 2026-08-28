"""
同步领域实体
包含目录同步配置实体
"""

import os
from dataclasses import dataclass, fields
from typing import Any, Optional


@dataclass
class SyncPathEntity:
    """目录同步路径实体"""

    id: int
    source: str
    dest: str
    unknown: str
    mode: str
    compatibility: bool
    rename: bool
    enabled: bool
    note: str | None
    operation: str | None = None
    src_backend: str | None = None
    dst_backend: str | None = None

    _VALID_MODES = {"copy", "move", "link", "softlink"}

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    @property
    def is_valid_mode(self) -> bool:
        """同步模式是否有效"""
        return self.mode in self._VALID_MODES

    @property
    def is_link_mode(self) -> bool:
        """是否为硬链接模式"""
        return self.mode == "link"

    @property
    def has_dest(self) -> bool:
        """是否配置了目标目录"""
        return bool(self.dest)

    @property
    def has_unknown(self) -> bool:
        """是否配置了未识别目录"""
        return bool(self.unknown)

    @property
    def is_valid(self) -> bool:
        """同步路径配置是否有效"""
        return bool(self.source) and self.source not in ("/", "\\") and self.is_valid_mode

    @property
    def requires_cross_device_check(self) -> bool:
        """链接模式是否需要跨设备检查"""
        return self.is_link_mode and self.has_dest

    @classmethod
    def from_orm(cls, orm_model) -> Optional["SyncPathEntity"]:
        if orm_model is None:
            return None
        return cls(
            id=orm_model.ID,
            source=orm_model.SOURCE or "",
            dest=orm_model.DEST or "",
            unknown=orm_model.UNKNOWN or "",
            mode=orm_model.MODE or "",
            compatibility=bool(orm_model.COMPATIBILITY),
            rename=bool(orm_model.RENAME),
            enabled=bool(orm_model.ENABLED),
            note=orm_model.NOTE,
            operation=getattr(orm_model, "OPERATION", None),
            src_backend=getattr(orm_model, "SRC_BACKEND", None),
            dst_backend=getattr(orm_model, "DST_BACKEND", None),
        )

    _ORM_FIELD_MAP = {}

    def validate(self) -> list[str]:
        """验证同步路径配置，返回错误信息列表（空列表表示验证通过）"""
        errors = []
        if not self.source:
            errors.append("源目录不能为空")
        elif self.source in ("/", "\\"):
            errors.append("源目录不能是根目录")
        if self.mode and self.mode not in self._VALID_MODES:
            errors.append(f"无效的同步模式: {self.mode}")
        return errors

    @staticmethod
    def validate_hardlink(source: str, dest: str) -> str | None:
        """校验硬链接是否跨盘，返回错误信息或 None"""
        if not dest:
            return None
        common = os.path.commonprefix([source, dest])
        if not common or common == "/":
            return "硬链接不能跨盘"
        return None

    @staticmethod
    def is_subpath(parent: str, child: str) -> bool:
        """判断 child 路径是否在 parent 路径之下"""
        parent = os.path.normpath(parent)
        child = os.path.normpath(child)
        return child == parent or child.startswith(parent + os.sep)

    def __getattr__(self, name: str):
        """兼容旧代码的大写属性访问"""
        lower_name = name.lower()
        field_name = self._ORM_FIELD_MAP.get(lower_name, lower_name)
        if field_name in {f.name for f in fields(self)}:
            return getattr(self, field_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "dest": self.dest,
            "unknown": self.unknown,
            "mode": self.mode,
            "compatibility": self.compatibility,
            "rename": self.rename,
            "enabled": self.enabled,
            "note": self.note,
        }
