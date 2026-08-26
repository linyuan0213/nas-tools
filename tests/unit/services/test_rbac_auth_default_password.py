"""RBACAuthService.is_default_password 判定测试."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure.security import generate_password_hash
from app.services.rbac.auth_service import RBACAuthService


def _make_svc(password: str | None):
    user_repo = MagicMock()
    user_repo.get_user_by_id.return_value = SimpleNamespace(
        ID=1,
        PASSWORD_HASH=generate_password_hash(password) if password else "",
    )
    return RBACAuthService(user_repo, MagicMock())


class TestIsDefaultPassword:
    def test_default_password_detected(self):
        """使用内置默认密码 → 应提示"""
        svc = _make_svc("password")
        with patch("app.services.rbac.auth_service.settings") as mock_settings:
            mock_settings.get.return_value = {}
            assert svc.is_default_password(1) is True

    def test_changed_password_not_detected(self):
        """已修改密码 → 不提示"""
        svc = _make_svc("MyStr0ng!Pass")
        with patch("app.services.rbac.auth_service.settings") as mock_settings:
            mock_settings.get.return_value = {}
            assert svc.is_default_password(1) is False

    def test_custom_initial_password_not_prompted(self):
        """部署时自定义了初始密码 → 不提示"""
        svc = _make_svc("CustomInit@123")
        with patch("app.services.rbac.auth_service.settings") as mock_settings:
            mock_settings.get.return_value = {"login_password": "CustomInit@123"}
            assert svc.is_default_password(1) is False

    def test_hash_marker_config_still_checks_default(self):
        """配置为 [hash] 历史标记时仍按内置默认密码判定"""
        svc = _make_svc("password")
        with patch("app.services.rbac.auth_service.settings") as mock_settings:
            mock_settings.get.return_value = {"login_password": "[hash]xxxx"}
            assert svc.is_default_password(1) is True

    def test_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_user_by_id.return_value = None
        svc = RBACAuthService(user_repo, MagicMock())
        assert svc.is_default_password(999) is False
