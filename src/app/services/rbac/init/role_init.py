"""RBAC 角色初始化."""

import log
from app.db.repositories.rbac_repo_adapter import (
    RBACMenuRepositoryAdapter,
    RBACPermissionRepositoryAdapter,
    RBACRoleRepositoryAdapter,
)
from app.services.rbac.init.constants import DEFAULT_ROLES


def init_rbac_roles(
    role_repo=None,
    permission_repo=None,
    menu_repo=None,
):
    """初始化角色数据"""
    role_repo = role_repo or RBACRoleRepositoryAdapter()
    permission_repo = permission_repo or RBACPermissionRepositoryAdapter()
    menu_repo = menu_repo or RBACMenuRepositoryAdapter()
    created_count = 0

    for role_data in DEFAULT_ROLES:
        existing = role_repo.get_role_by_code(role_data["code"])
        role_id = None
        if not existing:
            role = role_repo.create_role(
                role_name=role_data["name"],
                role_code=role_data["code"],
                description=role_data["description"],
                role_level=role_data["level"],
            )
            created_count += 1
            log.info(f"[RBAC]创建角色: {role_data['name']}")
            role_id = role.ID
        else:
            role_id = existing.ID

        # all_permissions 标记的角色自动赋予当前系统所有权限，不依赖静态权限列表
        if role_data.get("all_permissions"):
            all_perms = permission_repo.get_all_permissions()
            permission_ids = [p.ID for p in all_perms]
            if permission_ids:
                role_repo.assign_permissions_to_role(role_id, permission_ids)
                log.info(f"[RBAC]为角色 {role_data['name']} 赋予全部 {len(permission_ids)} 个权限")
        elif role_data["permissions"] and not existing:
            permissions = permission_repo.get_permissions_by_codes(role_data["permissions"])
            permission_ids = [p.ID for p in permissions]
            if permission_ids:
                role_repo.assign_permissions_to_role(role_id, permission_ids)
                log.info(f"[RBAC]为角色 {role_data['name']} 分配 {len(permission_ids)} 个权限")

        if role_data["menus"] and not existing:
            menu_ids = []
            for menu_code in role_data["menus"]:
                menu = menu_repo.get_menu_by_code(menu_code)
                if menu:
                    menu_ids.append(menu.ID)
            if menu_ids:
                role_repo.assign_menus_to_role(role_id, menu_ids)
                log.info(f"[RBAC]为角色 {role_data['name']} 分配 {len(menu_ids)} 个菜单")
        elif role_data.get("all_permissions"):
            # all_permissions 标记的角色同时拥有所有菜单
            all_menus = menu_repo.get_all_menus()
            menu_ids = [m.ID for m in all_menus]
            if menu_ids:
                role_repo.assign_menus_to_role(role_id, menu_ids)
                log.info(f"[RBAC]为角色 {role_data['name']} 赋予全部 {len(menu_ids)} 个菜单")

    log.info(f"[RBAC]角色初始化完成，新增 {created_count} 个角色")
    return created_count
