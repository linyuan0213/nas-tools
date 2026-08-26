"""
RBAC 领域 Repository 适配器
将旧版 RBACRepository 适配为新领域接口
"""

from typing import cast

from app.db.repositories.rbac.rbac_user_repository import RBACUserRepository
from app.domain.entities.rbac import (
    RBACRoleEntity,
    RBACUserEntity,
)
from app.domain.interfaces.rbac_repo import (
    IRBACUserRepository,
)


class RBACUserRepositoryAdapter(IRBACUserRepository):
    """RBAC用户仓储适配器"""

    def __init__(self, repo: RBACUserRepository | None = None):
        self._repo = repo or RBACUserRepository()

    def get_user_by_id(self, user_id: int) -> RBACUserEntity | None:
        row = self._repo.get_user_by_id(user_id)
        return RBACUserEntity.from_orm(row)

    def get_user_by_username(self, username: str) -> RBACUserEntity | None:
        row = self._repo.get_user_by_username(username)
        return RBACUserEntity.from_orm(row)

    def get_user_by_email(self, email: str) -> RBACUserEntity | None:
        row = self._repo.get_user_by_email(email)
        return RBACUserEntity.from_orm(row)

    def get_users(
        self, page: int = 1, page_size: int = 20, status: int | None = None
    ) -> tuple[list[RBACUserEntity], int]:
        rows, total = self._repo.get_users(page=page, page_size=page_size, status=status)
        return [e for e in [RBACUserEntity.from_orm(r) for r in rows] if e is not None], total

    def get_all_users(self) -> list[RBACUserEntity]:
        rows = self._repo.get_all_users()
        return [e for e in [RBACUserEntity.from_orm(r) for r in rows] if e is not None]

    def is_user_exists(self, username: str) -> bool:
        return self._repo.is_user_exists(username)

    def is_email_exists(self, email: str) -> bool:
        return self._repo.is_email_exists(email)

    def create_user(
        self,
        username: str,
        password_hash: str,
        email: str | None = None,
        nickname: str | None = None,
    ) -> RBACUserEntity:
        row = self._repo.create_user(username, password_hash, email, nickname)
        if isinstance(row, bool):
            row = self._repo.get_user_by_username(username)
        return cast(RBACUserEntity, RBACUserEntity.from_orm(row))

    def update_user(self, user_id: int, **kwargs) -> bool:
        return self._repo.update_user(user_id, **kwargs)

    def update_last_login(self, user_id: int, ip: str | None = None) -> bool:
        return self._repo.update_last_login(user_id, ip)

    def delete_user(self, user_id: int) -> bool:
        return self._repo.delete_user(user_id)

    def hard_delete_user(self, user_id: int) -> bool:
        return self._repo.hard_delete_user(user_id)

    def get_user_roles(self, user_id: int) -> list[RBACRoleEntity]:
        rows = self._repo.get_user_roles(user_id)
        return [e for e in [RBACRoleEntity.from_orm(r) for r in rows] if e is not None]

    def assign_roles_to_user(self, user_id: int, role_ids: list[int]) -> bool:
        return self._repo.assign_roles_to_user(user_id, role_ids)

    def add_role_to_user(self, user_id: int, role_id: int) -> bool:
        return self._repo.add_role_to_user(user_id, role_id)

    def remove_role_from_user(self, user_id: int, role_id: int) -> bool:
        return self._repo.remove_role_from_user(user_id, role_id)
