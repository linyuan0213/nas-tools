"""
RBAC Repository
基于角色的访问控制(RBAC)数据访问层
处理用户、角色、权限、菜单的数据库操作
"""

from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from app.db.models.rbac import (
    RBACMenu,
    RBACPermission,
    RBACRole,
)
from app.db.repositories.base_repository import BaseRepository


class RBACRoleRepository(BaseRepository):
    """
    RBAC角色管理仓储
    """

    def _get_role_by_id(self, db: Session, role_id: int) -> RBACRole | None:
        """在同一 session 内根据ID获取角色。"""
        return (
            db.query(RBACRole)
            .options(
                selectinload(RBACRole.permissions),
                selectinload(RBACRole.menus),
                selectinload(RBACRole.users),
            )
            .filter(RBACRole.ID == role_id)
            .first()
        )

    def get_role_by_id(self, role_id: int) -> RBACRole | None:
        """
        根据ID获取角色

        Args:
            role_id: 角色ID

        Returns:
            角色对象或None
        """
        with self.session() as db:
            return self._get_role_by_id(db, role_id)

    def get_role_by_code(self, role_code: str) -> RBACRole | None:
        """
        根据角色代码获取角色

        Args:
            role_code: 角色代码

        Returns:
            角色对象或None
        """
        with self.session() as db:
            return (
                db.query(RBACRole)
                .options(
                    selectinload(RBACRole.permissions),
                    selectinload(RBACRole.menus),
                    selectinload(RBACRole.users),
                )
                .filter(RBACRole.ROLE_CODE == role_code, RBACRole.STATUS == 1)
                .first()
            )

    def get_all_roles(self, status: int | None = None) -> list[RBACRole]:
        """
        获取所有角色（预加载权限、菜单、用户关联）

        Args:
            status: 状态筛选

        Returns:
            角色列表
        """
        with self.session() as db:
            query = db.query(RBACRole).options(
                selectinload(RBACRole.permissions),
                selectinload(RBACRole.menus),
                selectinload(RBACRole.users),
            )
            if status is not None:
                query = query.filter(RBACRole.STATUS == status)
            return query.order_by(RBACRole.ROLE_LEVEL).all()

    def get_roles_page(self, page: int = 1, page_size: int = 20) -> tuple:
        """
        分页获取角色列表

        Args:
            page: 页码
            page_size: 每页数量

        Returns:
            (角色列表, 总数)
        """
        with self.session() as db:
            query = db.query(RBACRole).filter(RBACRole.STATUS == 1)
            total = query.count()
            roles = (
                query.options(
                    selectinload(RBACRole.permissions),
                    selectinload(RBACRole.menus),
                    selectinload(RBACRole.users),
                )
                .order_by(RBACRole.ROLE_LEVEL)
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return roles, total

    def is_role_exists(self, role_code: str) -> bool:
        """
        检查角色代码是否已存在

        Args:
            role_code: 角色代码

        Returns:
            是否存在
        """
        with self.session() as db:
            count = db.query(RBACRole).filter(RBACRole.ROLE_CODE == role_code).count()
            return count > 0

    def is_role_name_exists(self, role_name: str) -> bool:
        """
        检查角色名称是否已存在

        Args:
            role_name: 角色名称

        Returns:
            是否存在
        """
        with self.session() as db:
            count = db.query(RBACRole).filter(RBACRole.ROLE_NAME == role_name).count()
            return count > 0

    def create_role(
        self, role_name: str, role_code: str, description: str | None = None, role_level: int = 100
    ) -> RBACRole:
        """
        创建角色

        Args:
            role_name: 角色名称
            role_code: 角色代码
            description: 角色描述
            role_level: 角色级别

        Returns:
            创建的角色对象
        """
        with self.session() as db:
            role = RBACRole(
                ROLE_NAME=role_name, ROLE_CODE=role_code, DESCRIPTION=description, ROLE_LEVEL=role_level, STATUS=1
            )
            db.add(role)
            db.commit()
            # commit 后会话关闭会返回游离实例，懒加载 permissions/menus/users 会报
            # DetachedInstanceError；重新查询并预加载关系后再返回
            return (
                db.query(RBACRole)
                .options(
                    selectinload(RBACRole.permissions),
                    selectinload(RBACRole.menus),
                    selectinload(RBACRole.users),
                )
                .filter(RBACRole.ID == role.ID)
                .first()
            )

    def update_role(self, role_id: int, **kwargs) -> bool:
        """
        更新角色信息

        Args:
            role_id: 角色ID
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        with self.session() as db:
            role = self._get_role_by_id(db, role_id)
            if not role:
                return False

            allowed_fields = ["ROLE_NAME", "DESCRIPTION", "ROLE_LEVEL", "STATUS"]
            for key, value in kwargs.items():
                if key.upper() in allowed_fields:
                    setattr(role, key.upper(), value)

            role.UPDATED_AT = datetime.now()  # type: ignore[assignment]
            db.commit()
            return True

    def delete_role(self, role_id: int) -> bool:
        """
        删除角色

        Args:
            role_id: 角色ID

        Returns:
            是否成功
        """
        with self.session() as db:
            result = db.query(RBACRole).filter(RBACRole.ID == role_id).delete()
            db.commit()
            return result > 0

    # ========== 角色权限关联操作 ==========

    def get_role_permissions(self, role_id: int) -> list[RBACPermission]:
        """
        获取角色的权限列表

        Args:
            role_id: 角色ID

        Returns:
            权限列表
        """
        with self.session() as db:
            role = self._get_role_by_id(db, role_id)
            if not role:
                return []
            return list(role.permissions)

    def assign_permissions_to_role(self, role_id: int, permission_ids: list[int]) -> bool:
        """
        为角色分配权限

        Args:
            role_id: 角色ID
            permission_ids: 权限ID列表

        Returns:
            是否成功
        """
        with self.session() as db:
            role = self._get_role_by_id(db, role_id)
            if not role:
                return False

            permissions = (
                db.query(RBACPermission).filter(RBACPermission.ID.in_(permission_ids), RBACPermission.STATUS == 1).all()
            )

            role.permissions = permissions
            db.commit()
            return True

    # ========== 角色菜单关联操作 ==========

    def get_role_menus(self, role_id: int) -> list[RBACMenu]:
        """
        获取角色的菜单列表

        Args:
            role_id: 角色ID

        Returns:
            菜单列表
        """
        with self.session() as db:
            role = self._get_role_by_id(db, role_id)
            if not role:
                return []
            return list(role.menus)

    def assign_menus_to_role(self, role_id: int, menu_ids: list[int]) -> bool:
        """
        为角色分配菜单

        Args:
            role_id: 角色ID
            menu_ids: 菜单ID列表

        Returns:
            是否成功
        """
        with self.session() as db:
            role = self._get_role_by_id(db, role_id)
            if not role:
                return False

            menus = db.query(RBACMenu).filter(RBACMenu.ID.in_(menu_ids), RBACMenu.STATUS == 1).all()

            role.menus = menus
            db.commit()
            return True
