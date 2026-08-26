"""RBAC auth service - 用户认证."""

from app.core.settings import settings
from app.infrastructure.security import check_password_hash, generate_password_hash


class RBACAuthService:
    """用户认证服务"""

    def __init__(self, user_repo, log_repo):
        self.user_repo = user_repo
        self.log_repo = log_repo

    def authenticate_user(
        self, username: str, password: str, login_ip: str | None = None, user_agent: str | None = None
    ) -> tuple:
        """用户认证"""
        user = self.user_repo.get_user_by_username(username)

        if not user:
            self.log_repo.add_login_log(
                user_id=None,
                username=username,
                login_ip=login_ip,
                user_agent=user_agent,
                login_status=0,
                fail_reason="用户不存在",
            )
            return False, "用户名或密码错误"

        if user.STATUS != 1:
            self.log_repo.add_login_log(
                user_id=user.ID,
                username=username,
                login_ip=login_ip,
                user_agent=user_agent,
                login_status=0,
                fail_reason="用户已被禁用",
            )
            return False, "用户已被禁用"

        if not user.PASSWORD_HASH:
            default_password = settings.get("app").get("login_password") or "password"
            if password != default_password:
                self.log_repo.add_login_log(
                    user_id=user.ID,
                    username=username,
                    login_ip=login_ip,
                    user_agent=user_agent,
                    login_status=0,
                    fail_reason="密码错误",
                )
                return False, "用户名或密码错误"
            new_hash = generate_password_hash(password)
            self.user_repo.update_user(user.ID, PASSWORD_HASH=new_hash)
        elif not check_password_hash(user.PASSWORD_HASH, password):
            self.log_repo.add_login_log(
                user_id=user.ID,
                username=username,
                login_ip=login_ip,
                user_agent=user_agent,
                login_status=0,
                fail_reason="密码错误",
            )
            return False, "用户名或密码错误"

        self.user_repo.update_last_login(user.ID, login_ip)
        self.log_repo.add_login_log(
            user_id=user.ID, username=username, login_ip=login_ip, user_agent=user_agent, login_status=1
        )
        return True, user

    def change_password(self, user_id: int, old_password: str, new_password: str) -> tuple:
        """修改密码"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            return False, "用户不存在"
        if not check_password_hash(user.PASSWORD_HASH, old_password):
            return False, "原密码错误"
        new_password_hash = generate_password_hash(new_password)
        success = self.user_repo.update_user(user_id, PASSWORD_HASH=new_password_hash)
        if success:
            return True, "密码修改成功"
        return False, "密码修改失败"

    def is_default_password(self, user_id: int) -> bool:
        """当前密码是否仍为初始默认密码（用于提示用户尽快修改）.

        仅当未自定义初始密码（即使用内置默认值 "password"）时才判定；
        部署者通过 APP__LOGIN_PASSWORD 自定义的初始密码视为有意设置，不提示。
        """
        user = self.user_repo.get_user_by_id(user_id)
        if not user or not user.PASSWORD_HASH:
            return False
        configured_pwd = settings.get("app").get("login_password") or ""
        is_custom_initial = (
            bool(configured_pwd) and not configured_pwd.startswith("[hash]") and configured_pwd != "password"
        )
        if is_custom_initial:
            return False
        return check_password_hash(user.PASSWORD_HASH, "password")

    def reset_password(self, user_id: int, new_password: str, old_password: str | None = None) -> tuple:
        """重置密码"""
        user = self.user_repo.get_user_by_id(user_id)
        if not user:
            return False, "用户不存在"
        if old_password is not None:
            if not user.PASSWORD_HASH:
                default_password = settings.get("app").get("login_password") or "password"
                if old_password != default_password:
                    return False, "旧密码错误"
            elif not check_password_hash(user.PASSWORD_HASH, old_password):
                return False, "旧密码错误"
        new_password_hash = generate_password_hash(new_password)
        success = self.user_repo.update_user(user_id, PASSWORD_HASH=new_password_hash)
        if success:
            return True, "密码修改成功"
        return False, "密码修改失败"
