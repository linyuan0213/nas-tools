"""RBAC 用户/角色删除保护测试."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ServiceError
from app.services.rbac.role_service import RBACRoleService
from app.services.rbac.user_service import SUPERADMIN_ROLE_CODE, RBACUserService

SUPERADMIN_ROLE = SimpleNamespace(id=1, role_code=SUPERADMIN_ROLE_CODE, status=1)
NORMAL_ROLE = SimpleNamespace(id=2, role_code="user", status=1)


def _user(uid: int, username: str, status: int = 1):
    return SimpleNamespace(id=uid, username=username, status=status, USERNAME=username)


def _make_user_service(role_map: dict[int, list], all_users: list):
    repo = MagicMock()
    repo.get_user_roles.side_effect = lambda uid: role_map.get(uid, [])
    repo.get_all_users.return_value = all_users
    repo.delete_user.return_value = True
    return RBACUserService(repo)


class TestDeleteUserProtection:
    def test_delete_last_superadmin_forbidden(self):
        """最后一个超级管理员不可删除"""
        svc = _make_user_service(
            role_map={1: [SUPERADMIN_ROLE], 2: [NORMAL_ROLE]},
            all_users=[_user(1, "admin"), _user(2, "normal")],
        )
        svc.user_repo.get_user_by_id.return_value = _user(1, "admin")
        with pytest.raises(ServiceError, match="最后一个超级管理员"):
            svc.delete_user(1)

    def test_delete_superadmin_allowed_when_another_exists(self):
        """存在其他启用超管时可删除"""
        svc = _make_user_service(
            role_map={1: [SUPERADMIN_ROLE], 2: [SUPERADMIN_ROLE]},
            all_users=[_user(1, "admin"), _user(2, "admin2")],
        )
        svc.user_repo.get_user_by_id.return_value = _user(1, "admin")
        svc.delete_user(1)
        svc.user_repo.delete_user.assert_called_once_with(1)

    def test_delete_self_forbidden(self):
        """不能删除当前登录用户"""
        svc = _make_user_service(role_map={1: [SUPERADMIN_ROLE]}, all_users=[_user(1, "admin")])
        svc.user_repo.get_user_by_id.return_value = _user(1, "admin")
        with pytest.raises(ServiceError, match="当前登录用户"):
            svc.delete_user(1, current_user_id=1)

    def test_delete_normal_user_allowed(self):
        """普通用户正常删除"""
        svc = _make_user_service(
            role_map={1: [SUPERADMIN_ROLE], 2: [NORMAL_ROLE]},
            all_users=[_user(1, "admin"), _user(2, "normal")],
        )
        svc.user_repo.get_user_by_id.return_value = _user(2, "normal")
        svc.delete_user(2, current_user_id=1)
        svc.user_repo.delete_user.assert_called_once_with(2)


class TestRoleProtection:
    def _make_role_service(self, role):
        repo = MagicMock()
        repo.get_role_by_id.return_value = role
        return RBACRoleService(repo)

    def test_delete_superadmin_role_forbidden(self):
        svc = self._make_role_service(SimpleNamespace(ROLE_CODE="superadmin", ROLE_NAME="超级管理员"))
        with pytest.raises(ServiceError, match="不可删除"):
            svc.delete_role(1)

    def test_disable_superadmin_role_forbidden(self):
        svc = self._make_role_service(SimpleNamespace(ROLE_CODE="superadmin", ROLE_NAME="超级管理员"))
        with pytest.raises(ServiceError, match="不可禁用"):
            svc.update_role(1, status=0)

    def test_normal_role_deletable(self):
        svc = self._make_role_service(SimpleNamespace(ROLE_CODE="user", ROLE_NAME="普通用户"))
        svc.delete_role(2)
        svc.role_repo.delete_role.assert_called_once_with(2)
