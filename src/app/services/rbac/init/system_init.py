"""RBAC 系统初始化入口."""

from typing import Any

import log
from app.db.repositories.rbac_repo_adapter import RBACRoleRepositoryAdapter, RBACUserRepositoryAdapter
from app.infrastructure.security import generate_password_hash
from app.services.rbac.init.menu_init import init_rbac_menus
from app.services.rbac.init.permission_init import init_rbac_permissions
from app.services.rbac.init.role_init import init_rbac_roles


def init_rbac_system(
    permission_repo=None,
    menu_repo=None,
    role_repo=None,
):
    """
    初始化RBAC系统
    创建默认的权限、菜单、角色
    """
    try:
        log.info("[RBAC初始化]开始初始化RBAC系统...")
        init_rbac_permissions(permission_repo=permission_repo)
        init_rbac_menus(menu_repo=menu_repo)
        init_rbac_roles(role_repo=role_repo, permission_repo=permission_repo, menu_repo=menu_repo)
        log.info("[RBAC初始化]RBAC系统初始化完成")
        return True
    except Exception as e:
        log.error(f"[RBAC初始化]初始化失败: {e!s}")
        return False


def init_admin_user(
    admin_username: str,
    admin_password: str,
    user_repo: Any = None,
    role_repo: Any = None,
):
    """
    初始化管理员用户

    Args:
        admin_username: 管理员用户名
        admin_password: 管理员密码
    """
    user_repo = user_repo or RBACUserRepositoryAdapter()
    role_repo = role_repo or RBACRoleRepositoryAdapter()
    try:
        existing = user_repo.get_user_by_username(admin_username)
        if existing:
            old_hash = existing.PASSWORD_HASH or ""
            if old_hash.startswith(("pbkdf2:", "scrypt:")) or not old_hash:
                new_hash = generate_password_hash(admin_password)
                user_repo.update_user(existing.ID, password_hash=new_hash)
                log.info(f"[RBAC初始化]管理员用户 {admin_username} 密码已从旧格式迁移到 Argon2")
            else:
                log.info(f"[RBAC初始化]管理员用户 {admin_username} 已存在")
            return True

        # 系统中已有其他用户（管理员改名/删除过）→ 不再复活默认账号，避免安全隐患
        if user_repo.get_all_users():
            log.info(f"[RBAC初始化]系统已存在用户，跳过创建默认管理员 {admin_username}")
            return True

        password_hash = generate_password_hash(admin_password)

        user = user_repo.create_user(username=admin_username, password_hash=password_hash, nickname="系统管理员")

        superadmin_role = role_repo.get_role_by_code("superadmin")
        if superadmin_role:
            user_repo.assign_roles_to_user(user.ID, [superadmin_role.ID])

        log.info(f"[RBAC初始化]创建管理员用户: {admin_username}")
        return True
    except Exception as e:
        log.error(f"[RBAC初始化]创建管理员用户失败: {e!s}")
        return False
