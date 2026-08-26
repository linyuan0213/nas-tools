"""RBAC 初始化——默认管理员创建回归测试."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.rbac.init.system_init import init_admin_user


def _make_repos(existing_user=None, all_users=None):
    user_repo = MagicMock()
    user_repo.get_user_by_username.return_value = existing_user
    user_repo.get_all_users.return_value = all_users or ([existing_user] if existing_user else [])
    role_repo = MagicMock()
    role_repo.get_role_by_code.return_value = SimpleNamespace(ID=1)
    return user_repo, role_repo


class TestInitAdminUser:
    def test_create_when_no_users(self):
        """全新系统（无任何用户）→ 创建默认管理员"""
        user_repo, role_repo = _make_repos()
        assert init_admin_user("admin", "password", user_repo=user_repo, role_repo=role_repo)
        user_repo.create_user.assert_called_once()
        assert user_repo.create_user.call_args.kwargs["username"] == "admin"

    def test_skip_when_other_users_exist(self):
        """已有其他用户（管理员被改名/删除）→ 不得复活默认账号"""
        user_repo, role_repo = _make_repos(
            all_users=[SimpleNamespace(ID=1, USERNAME="linyuan213", PASSWORD_HASH="$argon2id$xxx")]
        )
        assert init_admin_user("admin", "password", user_repo=user_repo, role_repo=role_repo)
        user_repo.create_user.assert_not_called()
        user_repo.update_user.assert_not_called()

    def test_existing_admin_argon2_not_reset(self):
        """管理员存在且已是 Argon2 哈希 → 不重置密码"""
        user = SimpleNamespace(ID=1, USERNAME="admin", PASSWORD_HASH="$argon2id$v=19$xxx")
        user_repo, role_repo = _make_repos(existing_user=user)
        assert init_admin_user("admin", "password", user_repo=user_repo, role_repo=role_repo)
        user_repo.update_user.assert_not_called()
        user_repo.create_user.assert_not_called()

    def test_existing_admin_legacy_hash_migrated(self):
        """管理员存在但为旧格式/空哈希 → 迁移为配置密码的 Argon2 哈希"""
        user = SimpleNamespace(ID=1, USERNAME="admin", PASSWORD_HASH="pbkdf2:sha256:xxx")
        user_repo, role_repo = _make_repos(existing_user=user)
        assert init_admin_user("admin", "password", user_repo=user_repo, role_repo=role_repo)
        user_repo.update_user.assert_called_once()
        new_hash = user_repo.update_user.call_args.kwargs["password_hash"]
        assert new_hash.startswith("$argon2")

    def test_existing_admin_empty_hash_migrated(self):
        user = SimpleNamespace(ID=1, USERNAME="admin", PASSWORD_HASH="")
        user_repo, role_repo = _make_repos(existing_user=user)
        assert init_admin_user("admin", "password", user_repo=user_repo, role_repo=role_repo)
        user_repo.update_user.assert_called_once()
