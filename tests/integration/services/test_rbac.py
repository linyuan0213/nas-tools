"""Tests for app.services.rbac package."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ResourceAlreadyExistsError, ResourceNotFoundError
from app.services.rbac.auth_service import RBACAuthService
from app.services.rbac.check_service import (
    RBACCheckService,
    require_any_permission,
    require_permission,
)
from app.services.rbac.menu_service import RBACMenuService
from app.services.rbac.permission_service import RBACPermissionService
from app.services.rbac.role_service import RBACRoleService
from app.services.rbac.user_service import RBACUserService


class TestRBACAuthService:
    """Test suite for RBACAuthService."""

    def test_authenticate_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_username.return_value = None
        log_repo = MagicMock()
        auth = RBACAuthService(user_repo, log_repo)

        result, msg = auth.authenticate_user("testuser", "password")
        assert result is False
        assert "用户名或密码错误" in msg
        log_repo.add_login_log.assert_called_once()
        assert log_repo.add_login_log.call_args.kwargs.get("user_id") is None

    def test_authenticate_user_disabled(self):
        user_repo = MagicMock()
        user = MagicMock()
        user.STATUS = 0
        user_repo.get_user_by_username.return_value = user
        log_repo = MagicMock()
        auth = RBACAuthService(user_repo, log_repo)

        result, msg = auth.authenticate_user("testuser", "password")
        assert result is False
        assert "用户已被禁用" in msg

    def test_authenticate_user_empty_password_match(self):
        user_repo = MagicMock()
        user = MagicMock()
        user.STATUS = 1
        user.PASSWORD_HASH = None
        user.ID = 1
        user_repo.get_user_by_username.return_value = user
        log_repo = MagicMock()
        auth = RBACAuthService(user_repo, log_repo)

        mock_settings = MagicMock()
        mock_settings.get.return_value = {"login_password": "password"}
        with patch("app.services.rbac.auth_service.settings", mock_settings):
            result, msg = auth.authenticate_user("testuser", "password")
            assert result is True
            user_repo.update_user.assert_called_once()

    def test_authenticate_user_empty_password_mismatch(self):
        user_repo = MagicMock()
        user = MagicMock()
        user.STATUS = 1
        user.PASSWORD_HASH = None
        user.ID = 1
        user_repo.get_user_by_username.return_value = user
        log_repo = MagicMock()
        auth = RBACAuthService(user_repo, log_repo)

        mock_settings = MagicMock()
        mock_settings.get.return_value = {"login_password": "password"}
        with patch("app.services.rbac.auth_service.settings", mock_settings):
            result, msg = auth.authenticate_user("testuser", "wrongpass")
            assert result is False

    def test_change_password_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        auth = RBACAuthService(user_repo, MagicMock())

        result, msg = auth.change_password(1, "old", "new")
        assert result is False
        assert "用户不存在" in msg

    def test_reset_password_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        auth = RBACAuthService(user_repo, MagicMock())

        result, msg = auth.reset_password(1, "newpass")
        assert result is False
        assert "用户不存在" in msg


class TestRBACUserService:
    """Test suite for RBACUserService."""

    def test_create_user_exists(self):
        user_repo = MagicMock()
        user_repo.is_user_exists.return_value = True
        svc = RBACUserService(user_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="用户名已存在"):
            svc.create_user("testuser", "password")

    def test_create_user_email_taken(self):
        user_repo = MagicMock()
        user_repo.is_user_exists.return_value = False
        user_repo.is_email_exists.return_value = True
        svc = RBACUserService(user_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="邮箱已被使用"):
            svc.create_user("testuser", "password", email="test@test.com")

    def test_create_user_success(self):
        user_repo = MagicMock()
        user_repo.is_user_exists.return_value = False
        user_repo.is_email_exists.return_value = False
        user = MagicMock()
        user.ID = 1
        user_repo.create_user.return_value = user
        svc = RBACUserService(user_repo)

        result = svc.create_user("testuser", "password")
        assert result == user

    def test_update_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACUserService(user_repo)

        with pytest.raises(ResourceNotFoundError, match="用户不存在"):
            svc.update_user(1, nickname="new")

    def test_delete_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACUserService(user_repo)

        with pytest.raises(ResourceNotFoundError, match="用户不存在"):
            svc.delete_user(1)

    def test_get_user_roles_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACUserService(user_repo)

        result = svc.get_user_roles(1)
        assert result == []


class TestRBACRoleService:
    """Test suite for RBACRoleService."""

    def test_create_role_code_exists(self):
        role_repo = MagicMock()
        role_repo.is_role_exists.return_value = True
        svc = RBACRoleService(role_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="角色代码已存在"):
            svc.create_role("Admin", "admin")

    def test_create_role_name_exists(self):
        role_repo = MagicMock()
        role_repo.is_role_exists.return_value = False
        role_repo.is_role_name_exists.return_value = True
        svc = RBACRoleService(role_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="角色名称已存在"):
            svc.create_role("Admin", "admin")

    def test_create_role_success(self):
        role_repo = MagicMock()
        role_repo.is_role_exists.return_value = False
        role_repo.is_role_name_exists.return_value = False
        role = MagicMock()
        role.id = 1
        role_repo.create_role.return_value = role
        svc = RBACRoleService(role_repo)

        result = svc.create_role("Admin", "admin", permission_ids=[1, 2])
        assert result == role
        role_repo.assign_permissions_to_role.assert_called_once_with(1, [1, 2])

    def test_update_role_not_found(self):
        role_repo = MagicMock()
        role_repo.get_role_by_id.return_value = None
        svc = RBACRoleService(role_repo)

        with pytest.raises(ResourceNotFoundError, match="角色不存在"):
            svc.update_role(1, description="new")

    def test_delete_role_not_found(self):
        role_repo = MagicMock()
        role_repo.get_role_by_id.return_value = None
        svc = RBACRoleService(role_repo)

        with pytest.raises(ResourceNotFoundError, match="角色不存在"):
            svc.delete_role(1)

    def test_assign_permissions_role_not_found(self):
        role_repo = MagicMock()
        role_repo.get_role_by_id.return_value = None
        svc = RBACRoleService(role_repo)

        with pytest.raises(ResourceNotFoundError, match="角色不存在"):
            svc.assign_permissions_to_role(1, [1])


class TestRBACPermissionService:
    """Test suite for RBACPermissionService."""

    def test_create_permission_exists(self):
        perm_repo = MagicMock()
        perm_repo.get_permission_by_code.return_value = MagicMock()
        svc = RBACPermissionService(perm_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="权限代码已存在"):
            svc.create_permission("Test", "test:read")

    def test_create_permission_success(self):
        perm_repo = MagicMock()
        perm_repo.get_permission_by_code.return_value = None
        perm = MagicMock()
        perm_repo.create_permission.return_value = perm
        svc = RBACPermissionService(perm_repo)

        result = svc.create_permission("Test", "test:read")
        assert result == perm

    def test_update_permission_not_found(self):
        perm_repo = MagicMock()
        perm_repo.get_permission_by_id.return_value = None
        svc = RBACPermissionService(perm_repo)

        with pytest.raises(ResourceNotFoundError, match="权限不存在"):
            svc.update_permission(1, description="new")

    def test_delete_permission_not_found(self):
        perm_repo = MagicMock()
        perm_repo.get_permission_by_id.return_value = None
        svc = RBACPermissionService(perm_repo)

        with pytest.raises(ResourceNotFoundError, match="权限不存在"):
            svc.delete_permission(1)


class TestRBACMenuService:
    """Test suite for RBACMenuService."""

    def test_create_menu_exists(self):
        menu_repo = MagicMock()
        menu_repo.get_menu_by_code.return_value = MagicMock()
        user_repo = MagicMock()
        svc = RBACMenuService(menu_repo, user_repo)

        with pytest.raises(ResourceAlreadyExistsError, match="菜单代码已存在"):
            svc.create_menu("Dashboard", "dashboard")

    def test_create_menu_success(self):
        menu_repo = MagicMock()
        menu_repo.get_menu_by_code.return_value = None
        menu = MagicMock()
        menu_repo.create_menu.return_value = menu
        user_repo = MagicMock()
        svc = RBACMenuService(menu_repo, user_repo)

        result = svc.create_menu("Dashboard", "dashboard")
        assert result == menu

    def test_update_menu_not_found(self):
        menu_repo = MagicMock()
        menu_repo.get_menu_by_id.return_value = None
        user_repo = MagicMock()
        svc = RBACMenuService(menu_repo, user_repo)

        with pytest.raises(ResourceNotFoundError, match="菜单不存在"):
            svc.update_menu(1, name="new")

    def test_get_user_menus_superadmin(self):
        menu_repo = MagicMock()
        user_repo = MagicMock()
        menu = MagicMock()
        menu.ID = 1
        menu.PARENT_ID = None
        menu.MENU_NAME = "Dashboard"
        menu.MENU_CODE = "dashboard"
        menu.PATH = "/dashboard"
        menu.ICON = "dashboard"
        menu.SORT_ORDER = 0
        menu.PERMISSION_CODE = None
        menu.COMPONENT = None
        menu_repo.get_user_menus.return_value = [menu]
        svc = RBACMenuService(menu_repo, user_repo)

        result = svc.get_user_menus(1)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["path"] == "/dashboard"

    def test_get_user_menus_normal_user(self):
        menu_repo = MagicMock()
        user_repo = MagicMock()
        user = MagicMock()
        user_repo.get_user_by_id.return_value = user
        menu = MagicMock()
        menu.ID = 1
        menu.PARENT_ID = None
        menu.MENU_NAME = "Dashboard"
        menu.MENU_CODE = "dashboard"
        menu.PATH = "/dashboard"
        menu.ICON = None
        menu.SORT_ORDER = 0
        menu.PERMISSION_CODE = None
        menu.COMPONENT = None
        menu_repo.get_user_menus.return_value = [menu]
        svc = RBACMenuService(menu_repo, user_repo)

        result = svc.get_user_menus(1)
        assert isinstance(result, list)


class TestRBACCheckService:
    """Test suite for RBACCheckService."""

    @staticmethod
    def _mock_user_with_perms(user_repo, role_repo, user_id=1, permission_codes=None) -> RBACCheckService:
        """创建模拟的 RBACCheckService，user 拥有指定权限（通过角色驱动）。"""
        user_repo.get_user_by_id.return_value = MagicMock()
        if permission_codes:
            role = MagicMock()
            role.id = 99
            role.status = 1
            perms = []
            for code in permission_codes:
                p = MagicMock()
                p.permission_code = code
                p.status = 1
                perms.append(p)
            role_repo.get_role_permissions.return_value = perms
            user_repo.get_user_roles.return_value = [role]
        else:
            user_repo.get_user_roles.return_value = []
        return RBACCheckService(user_repo, role_repo, MagicMock(), MagicMock())

    def test_get_user_permissions_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACCheckService(user_repo, MagicMock(), MagicMock(), MagicMock())

        result = svc.get_user_permissions(1)
        assert result == set()

    def test_get_user_permissions_superadmin(self):
        user_repo = MagicMock()
        role_repo = MagicMock()
        svc = self._mock_user_with_perms(user_repo, role_repo, permission_codes=["test:read"])

        result = svc.get_user_permissions(1)
        assert "test:read" in result

    def test_check_permission_superadmin(self):
        user_repo = MagicMock()
        role_repo = MagicMock()
        svc = self._mock_user_with_perms(user_repo, role_repo, permission_codes=["any:perm"])

        assert svc.check_permission(1, "any:perm") is True

    def test_check_permission_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACCheckService(user_repo, MagicMock(), MagicMock(), MagicMock())

        assert svc.check_permission(1, "test:read") is False

    def test_check_any_permission_superadmin(self):
        user_repo = MagicMock()
        role_repo = MagicMock()
        svc = self._mock_user_with_perms(user_repo, role_repo, permission_codes=["a:1", "b:2"])

        assert svc.check_any_permission(1, ["a:1", "b:2"]) is True

    def test_check_all_permissions_superadmin(self):
        user_repo = MagicMock()
        role_repo = MagicMock()
        svc = self._mock_user_with_perms(user_repo, role_repo, permission_codes=["a:1", "b:2"])

        assert svc.check_all_permissions(1, ["a:1", "b:2"]) is True

    def test_check_menu_access_superadmin(self):
        user_repo = MagicMock()
        menu_repo = MagicMock()
        user_repo.get_user_by_id.return_value = MagicMock()
        menu = MagicMock()
        menu.MENU_CODE = "dashboard"
        menu_repo.get_user_menus.return_value = [menu]
        svc = RBACCheckService(user_repo, MagicMock(), MagicMock(), menu_repo)

        assert svc.check_menu_access(1, "dashboard") is True

    def test_check_menu_access_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACCheckService(user_repo, MagicMock(), MagicMock(), MagicMock())

        assert svc.check_menu_access(1, "dashboard") is False


class TestDecorators:
    """Test suite for backward-compatible decorators."""

    def test_require_permission_decorator(self):
        @require_permission("test:read")
        def dummy():
            return "ok"

        assert dummy() == "ok"

    def test_require_any_permission_decorator(self):
        @require_any_permission(["test:read", "test:write"])
        def dummy():
            return "ok"

        assert dummy() == "ok"
