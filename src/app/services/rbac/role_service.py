"""RBAC role service - 角色管理."""

from typing import cast

import log
from app.core.exceptions import ResourceAlreadyExistsError, ResourceNotFoundError, ServiceError
from app.db.models.rbac import RBACRole

SUPERADMIN_ROLE_CODE = "superadmin"


class RBACRoleService:
    """角色管理服务"""

    def __init__(self, role_repo):
        self.role_repo = role_repo

    def create_role(
        self,
        role_name: str,
        role_code: str,
        description: str | None = None,
        role_level: int = 100,
        permission_ids: list[int] | None = None,
        menu_ids: list[int] | None = None,
    ) -> RBACRole:
        """创建角色，成功返回角色对象，失败抛出异常."""
        if self.role_repo.is_role_exists(role_code):
            raise ResourceAlreadyExistsError(f"角色代码已存在: {role_code}")
        if self.role_repo.is_role_name_exists(role_name):
            raise ResourceAlreadyExistsError(f"角色名称已存在: {role_name}")
        role = self.role_repo.create_role(
            role_name=role_name, role_code=role_code, description=description, role_level=role_level
        )
        if not role:
            raise ResourceNotFoundError("创建角色失败，请检查数据是否重复")
        if permission_ids:
            self.role_repo.assign_permissions_to_role(role.id, permission_ids)
        if menu_ids:
            self.role_repo.assign_menus_to_role(role.id, menu_ids)
        log.info(f"[RBAC]创建角色成功: {role_name}")
        return role

    def update_role(self, role_id: int, **kwargs) -> None:
        """更新角色信息，失败抛出异常."""
        role = self.role_repo.get_role_by_id(role_id)
        if not role:
            raise ResourceNotFoundError(f"角色不存在: id={role_id}")
        # 内置超级管理员角色不可禁用（角色代码接口不提供修改，仅需拦截禁用）
        if (
            str(role.ROLE_CODE or "") == SUPERADMIN_ROLE_CODE
            and kwargs.get("status") is not None
            and kwargs["status"] != 1
        ):
            raise ServiceError("内置超级管理员角色不可禁用")
        success = self.role_repo.update_role(role_id, **kwargs)
        if not success:
            raise ResourceNotFoundError("更新失败")

    def delete_role(self, role_id: int) -> None:
        """删除角色，失败抛出异常."""
        role = self.role_repo.get_role_by_id(role_id)
        if not role:
            raise ResourceNotFoundError(f"角色不存在: id={role_id}")
        if str(role.ROLE_CODE or "") == SUPERADMIN_ROLE_CODE:
            raise ServiceError("内置超级管理员角色不可删除")
        success = self.role_repo.delete_role(role_id)
        if not success:
            raise ResourceNotFoundError("删除失败")
        log.info(f"[RBAC]删除角色: {role.ROLE_NAME}")

    def get_role_by_id(self, role_id: int) -> RBACRole | None:
        return cast(RBACRole | None, self.role_repo.get_role_by_id(role_id))

    def get_all_roles(self) -> list[RBACRole]:
        return cast(list[RBACRole], self.role_repo.get_all_roles(status=1))

    def assign_permissions_to_role(self, role_id: int, permission_ids: list[int]) -> None:
        """为角色分配权限，失败抛出异常."""
        role = self.role_repo.get_role_by_id(role_id)
        if not role:
            raise ResourceNotFoundError(f"角色不存在: id={role_id}")
        success = self.role_repo.assign_permissions_to_role(role_id, permission_ids)
        if not success:
            raise ResourceNotFoundError("权限分配失败")

    def assign_menus_to_role(self, role_id: int, menu_ids: list[int]) -> None:
        """为角色分配菜单，失败抛出异常."""
        role = self.role_repo.get_role_by_id(role_id)
        if not role:
            raise ResourceNotFoundError(f"角色不存在: id={role_id}")
        success = self.role_repo.assign_menus_to_role(role_id, menu_ids)
        if not success:
            raise ResourceNotFoundError("菜单分配失败")
