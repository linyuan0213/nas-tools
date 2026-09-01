"""存储后端插件的共享生命周期逻辑."""

import log
from app.db.repositories.storage_backend_repository import StorageBackendRepository


def disable_storage_records(stype: str) -> None:
    """禁用指定类型的存储后端记录（插件禁用时随动停用，配置保留，重新启用时恢复）"""
    try:
        repo = StorageBackendRepository()
        for s in repo.get_all() or []:
            if getattr(s, "TYPE", None) == stype and getattr(s, "ENABLED", False):
                repo.update(s.ID, ENABLED=0)
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]禁用存储后端记录失败 {stype}: {e}")
