"""RBAC 权限初始化."""

import log
from app.db.repositories.rbac_repo_adapter import RBACPermissionRepositoryAdapter
from app.services.rbac.init.constants import DEFAULT_PERMISSIONS


def init_rbac_permissions(
    permission_repo=None,
):
    """初始化权限数据"""
    permission_repo = permission_repo or RBACPermissionRepositoryAdapter()
    created_count = 0

    for perm_data in DEFAULT_PERMISSIONS:
        existing = permission_repo.get_permission_by_code(perm_data["code"])
        if not existing:
            permission_repo.create_permission(
                permission_name=perm_data["name"],
                permission_code=perm_data["code"],
                permission_type=perm_data["type"],
                module=perm_data["module"],
            )
            created_count += 1
            log.info(f"[RBAC]创建权限: {perm_data['name']}")

    log.info(f"[RBAC]权限初始化完成，新增 {created_count} 个权限")
    return created_count
