"""
RBAC Repository
基于角色的访问控制(RBAC)数据访问层
处理用户、角色、权限、菜单的数据库操作
"""

from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from app.db.models.rbac import (
    RBACRole,
    RBACUser,
)
from app.db.repositories.base_repository import BaseRepository


class RBACUserRepository(BaseRepository):
    """
    RBAC用户管理仓储
    """

    def _get_user_with_roles(self, db: Session, user_id: int) -> RBACUser | None:
        """在同一 session 内加载用户及完整角色数据。"""
        return (
            db.query(RBACUser)
            .options(
                selectinload(RBACUser.roles).selectinload(RBACRole.permissions),
                selectinload(RBACUser.roles).selectinload(RBACRole.menus),
                selectinload(RBACUser.roles).selectinload(RBACRole.users),
            )
            .filter(RBACUser.ID == user_id)
            .first()
        )

    def get_user_by_id(self, user_id: int) -> RBACUser | None:
        """
        根据ID获取用户（预加载角色）

        Args:
            user_id: 用户ID

        Returns:
            用户对象或None
        """
        with self.session() as db:
            return self._get_user_with_roles(db, user_id)

    def get_user_by_username(self, username: str) -> RBACUser | None:
        """
        根据用户名获取用户（不过滤状态，让上层判断）

        Args:
            username: 用户名

        Returns:
            用户对象或None
        """
        with self.session() as db:
            return (
                db.query(RBACUser)
                .options(
                    selectinload(RBACUser.roles).selectinload(RBACRole.permissions),
                    selectinload(RBACUser.roles).selectinload(RBACRole.menus),
                    selectinload(RBACUser.roles).selectinload(RBACRole.users),
                )
                .filter(RBACUser.USERNAME == username)
                .first()
            )

    def get_user_by_email(self, email: str) -> RBACUser | None:
        """
        根据邮箱获取用户

        Args:
            email: 邮箱地址

        Returns:
            用户对象或None
        """
        with self.session() as db:
            return db.query(RBACUser).filter(RBACUser.EMAIL == email, RBACUser.STATUS == 1).first()

    def get_users(self, page: int = 1, page_size: int = 20, status: int | None = None) -> tuple:
        """
        获取用户列表（支持分页，预加载角色）

        Args:
            page: 页码
            page_size: 每页数量
            status: 状态筛选

        Returns:
            (用户列表, 总数)
        """
        with self.session() as db:
            query = db.query(RBACUser).options(
                selectinload(RBACUser.roles).selectinload(RBACRole.permissions),
                selectinload(RBACUser.roles).selectinload(RBACRole.menus),
                selectinload(RBACUser.roles).selectinload(RBACRole.users),
            )

            if status is not None:
                query = query.filter(RBACUser.STATUS == status)

            total = query.count()
            users = query.offset((page - 1) * page_size).limit(page_size).all()
            for u in users:
                db.expunge(u)
            return users, total

    def get_all_users(self) -> list[RBACUser]:
        """获取所有用户（预加载完整角色数据）"""
        with self.session() as db:
            return (
                db.query(RBACUser)
                .options(
                    selectinload(RBACUser.roles).selectinload(RBACRole.permissions),
                    selectinload(RBACUser.roles).selectinload(RBACRole.menus),
                    selectinload(RBACUser.roles).selectinload(RBACRole.users),
                )
                .filter(RBACUser.STATUS == 1)
                .all()
            )

    def is_user_exists(self, username: str) -> bool:
        """
        检查用户名是否已存在

        Args:
            username: 用户名

        Returns:
            是否存在
        """
        with self.session() as db:
            count = db.query(RBACUser).filter(RBACUser.USERNAME == username).count()
            return count > 0

    def is_email_exists(self, email: str) -> bool:
        """
        检查邮箱是否已存在

        Args:
            email: 邮箱地址

        Returns:
            是否存在
        """
        with self.session() as db:
            count = db.query(RBACUser).filter(RBACUser.EMAIL == email).count()
            return count > 0

    def create_user(
        self,
        username: str,
        password_hash: str,
        email: str | None = None,
        nickname: str | None = None,
    ) -> RBACUser:
        """
        创建新用户

        Args:
            username: 用户名
            password_hash: 密码哈希
            email: 邮箱
            nickname: 昵称

        Returns:
            创建的用户对象
        """
        with self.session() as db:
            user = RBACUser(
                USERNAME=username,
                PASSWORD_HASH=password_hash,
                EMAIL=email,
                NICKNAME=nickname or username,
                STATUS=1,
            )
            db.add(user)
            db.commit()
            # commit 后会话关闭会返回游离实例，懒加载 roles 会报 DetachedInstanceError；
            # 重新查询并预加载关联后再返回
            return (
                db.query(RBACUser)
                .options(
                    selectinload(RBACUser.roles).selectinload(RBACRole.permissions),
                    selectinload(RBACUser.roles).selectinload(RBACRole.menus),
                    selectinload(RBACUser.roles).selectinload(RBACRole.users),
                )
                .filter(RBACUser.ID == user.ID)
                .first()
            )

    def update_user(self, user_id: int, **kwargs) -> bool:
        """
        更新用户信息

        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            if not user:
                return False

            allowed_fields = ["USERNAME", "EMAIL", "NICKNAME", "AVATAR", "STATUS", "PASSWORD_HASH"]
            for key, value in kwargs.items():
                if key.upper() in allowed_fields:
                    setattr(user, key.upper(), value)

            user.UPDATED_AT = datetime.now()  # type: ignore[assignment]
            db.commit()
            return True

    def update_last_login(self, user_id: int, ip: str | None = None) -> bool:
        """
        更新用户最后登录时间

        Args:
            user_id: 用户ID
            ip: 登录IP

        Returns:
            是否成功
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            if not user:
                return False

            user.LAST_LOGIN_AT = datetime.now()  # type: ignore[assignment]
            if ip:
                user.LAST_LOGIN_IP = ip  # type: ignore[assignment]
            db.commit()
            return True

    def delete_user(self, user_id: int) -> bool:
        """
        删除用户（硬删除）

        Args:
            user_id: 用户ID

        Returns:
            是否成功
        """
        with self.session() as db:
            result = db.query(RBACUser).filter(RBACUser.ID == user_id).delete()
            db.commit()
            return result > 0

    def hard_delete_user(self, user_id: int) -> bool:
        """
        硬删除用户

        Args:
            user_id: 用户ID

        Returns:
            是否成功
        """
        with self.session() as db:
            result = db.query(RBACUser).filter(RBACUser.ID == user_id).delete()
            db.commit()
            return result > 0

    # ========== 用户角色关联操作 ==========

    def get_user_roles(self, user_id: int) -> list[RBACRole]:
        """
        获取用户的角色列表

        Args:
            user_id: 用户ID

        Returns:
            角色列表
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            if not user:
                return []
            return list(user.roles)

    def assign_roles_to_user(self, user_id: int, role_ids: list[int]) -> bool:
        """
        为用户分配角色

        Args:
            user_id: 用户ID
            role_ids: 角色ID列表

        Returns:
            是否成功
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            if not user:
                return False

            roles = db.query(RBACRole).filter(RBACRole.ID.in_(role_ids), RBACRole.STATUS == 1).all()

            user.roles = roles
            db.commit()
            return True

    def add_role_to_user(self, user_id: int, role_id: int) -> bool:
        """
        为用户添加单个角色

        Args:
            user_id: 用户ID
            role_id: 角色ID

        Returns:
            是否成功
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            role = db.query(RBACRole).filter(RBACRole.ID == role_id).first()

            if not user or not role:
                return False

            if role not in user.roles:
                user.roles.append(role)

            db.commit()
            return True

    def remove_role_from_user(self, user_id: int, role_id: int) -> bool:
        """
        移除用户的角色

        Args:
            user_id: 用户ID
            role_id: 角色ID

        Returns:
            是否成功
        """
        with self.session() as db:
            user = self._get_user_with_roles(db, user_id)
            if not user:
                return False

            user.roles = [r for r in user.roles if role_id != r.ID]
            db.commit()
            return True
