"""RBAC Service Facade."""

from typing import Any

from app.db.repositories.rbac_repo_adapter import (
    RBACLogRepositoryAdapter,
    RBACMenuRepositoryAdapter,
    RBACPermissionRepositoryAdapter,
    RBACRoleRepositoryAdapter,
    RBACUserRepositoryAdapter,
)
from app.services.rbac.auth_service import RBACAuthService
from app.services.rbac.check_service import RBACCheckService
from app.services.rbac.menu_service import RBACMenuService
from app.services.rbac.permission_service import RBACPermissionService
from app.services.rbac.role_service import RBACRoleService
from app.services.rbac.user_service import RBACUserService


class RBACService:
    """
    RBAC服务 Facade
    提供用户管理、角色管理、权限管理、菜单管理等业务功能
    """

    def __init__(
        self,
        user_repo: Any = None,
        role_repo: Any = None,
        permission_repo: Any = None,
        menu_repo: Any = None,
        log_repo: RBACLogRepositoryAdapter | None = None,
    ):
        self.user_repo = user_repo or RBACUserRepositoryAdapter()
        self.role_repo = role_repo or RBACRoleRepositoryAdapter()
        self.permission_repo = permission_repo or RBACPermissionRepositoryAdapter()
        self.menu_repo = menu_repo or RBACMenuRepositoryAdapter()
        self.log_repo = log_repo or RBACLogRepositoryAdapter()

        self._auth = RBACAuthService(self.user_repo, self.log_repo)
        self._user = RBACUserService(self.user_repo)
        self._role = RBACRoleService(self.role_repo)
        self._permission = RBACPermissionService(self.permission_repo)
        self._menu = RBACMenuService(self.menu_repo, self.user_repo)
        self._check = RBACCheckService(self.user_repo, self.role_repo, self.permission_repo, self.menu_repo)

    # ==================== 用户认证（委托） ====================

    def authenticate_user(
        self, username: str, password: str, login_ip: str | None = None, user_agent: str | None = None
    ) -> tuple:
        return self._auth.authenticate_user(username, password, login_ip, user_agent)

    def change_password(self, user_id: int, old_password: str, new_password: str) -> tuple:
        return self._auth.change_password(user_id, old_password, new_password)

    def is_default_password(self, user_id: int) -> bool:
        return self._auth.is_default_password(user_id)

    def reset_password(self, user_id: int, new_password: str, old_password: str | None = None) -> tuple:
        return self._auth.reset_password(user_id, new_password, old_password)

    # ==================== 用户管理（委托） ====================

    def create_user(self, username: str, password: str, email=None, nickname=None, role_ids=None):
        return self._user.create_user(username, password, email, nickname, role_ids)

    def update_user(self, user_id: int, **kwargs) -> None:
        return self._user.update_user(user_id, **kwargs)

    def delete_user(self, user_id: int, current_user_id: int | None = None) -> None:
        return self._user.delete_user(user_id, current_user_id=current_user_id)

    def get_user_by_id(self, user_id: int):
        return self._user.get_user_by_id(user_id)

    def get_user_by_username(self, username: str):
        return self._user.get_user_by_username(username)

    def get_users(self, page: int = 1, page_size: int = 20):
        return self._user.get_users(page, page_size)

    def assign_roles_to_user(self, user_id: int, role_ids: list[int]) -> None:
        return self._user.assign_roles_to_user(user_id, role_ids)

    def get_user_roles(self, user_id: int):
        return self._user.get_user_roles(user_id)

    # ==================== 角色管理（委托） ====================

    def create_role(self, role_name, role_code, description=None, role_level=100, permission_ids=None, menu_ids=None):
        return self._role.create_role(role_name, role_code, description, role_level, permission_ids, menu_ids)

    def update_role(self, role_id: int, **kwargs) -> None:
        return self._role.update_role(role_id, **kwargs)

    def delete_role(self, role_id: int) -> None:
        return self._role.delete_role(role_id)

    def get_role_by_id(self, role_id: int):
        return self._role.get_role_by_id(role_id)

    def get_all_roles(self):
        return self._role.get_all_roles()

    def assign_permissions_to_role(self, role_id: int, permission_ids: list[int]) -> None:
        return self._role.assign_permissions_to_role(role_id, permission_ids)

    def assign_menus_to_role(self, role_id: int, menu_ids: list[int]) -> None:
        return self._role.assign_menus_to_role(role_id, menu_ids)

    # ==================== 权限管理（委托） ====================

    def create_permission(self, permission_name, permission_code, permission_type="api", module=None, description=None):
        return self._permission.create_permission(
            permission_name, permission_code, permission_type, module, description
        )

    def update_permission(self, permission_id: int, **kwargs) -> None:
        return self._permission.update_permission(permission_id, **kwargs)

    def delete_permission(self, permission_id: int) -> None:
        return self._permission.delete_permission(permission_id)

    def get_all_permissions(self, module=None):
        return self._permission.get_all_permissions(module)

    # ==================== 菜单管理（委托） ====================

    def create_menu(
        self,
        menu_name,
        menu_code,
        parent_id=None,
        path=None,
        icon=None,
        component=None,
        sort_order=0,
        menu_level=1,
        permission_code=None,
        **kwargs,
    ):
        return self._menu.create_menu(
            menu_name, menu_code, parent_id, path, icon, component, sort_order, menu_level, permission_code, **kwargs
        )

    def update_menu(self, menu_id: int, **kwargs) -> bool:
        self._menu.update_menu(menu_id, **kwargs)
        return True

    def delete_menu(self, menu_id: int) -> None:
        return self._menu.delete_menu(menu_id)

    def get_menu_tree(self, include_hidden: bool = False):
        return self._menu.get_menu_tree(include_hidden)

    def get_all_menus(self):
        return self._menu.get_all_menus()

    def reset_menus(self) -> int:
        return self._menu.reset_menus()

    def get_menu_by_id(self, menu_id: int):
        return self._menu.get_menu_by_id(menu_id)

    def get_user_menus(self, user_id: int):
        return self._menu.get_user_menus(user_id)

    # ==================== 权限检查（委托） ====================

    def get_user_permissions(self, user_id: int) -> set[str]:
        return self._check.get_user_permissions(user_id)

    def check_permission(self, user_id: int, permission_code: str) -> bool:
        return self._check.check_permission(user_id, permission_code)

    def check_any_permission(self, user_id: int, permission_codes: list[str]) -> bool:
        return self._check.check_any_permission(user_id, permission_codes)

    def check_all_permissions(self, user_id: int, permission_codes: list[str]) -> bool:
        return self._check.check_all_permissions(user_id, permission_codes)

    def check_menu_access(self, user_id: int, menu_code: str) -> bool:
        return self._check.check_menu_access(user_id, menu_code)
