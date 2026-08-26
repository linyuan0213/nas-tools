"""
JWT 认证路由
提供登录、刷新 Token、登出、获取当前用户信息
"""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from api.deps import get_auth_service, get_current_user, get_rbac_service
from app.core.error_codes import ErrorCode
from app.core.exceptions import AuthError
from app.core.settings import AppSettings
from app.schemas.auth import LoginResponse, UserContext
from app.schemas.common import CommonResponse
from app.services.auth_service import AuthService
from app.services.rbac_service import RBACService

_settings = AppSettings()

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    用户登录，返回 JWT Token 对。
    Refresh Token 通过 HttpOnly Cookie 返回。
    """
    user_ctx = auth_service.authenticate(form_data.username, form_data.password)
    if not user_ctx:
        raise AuthError(
            "用户名或密码错误",
            errcode=ErrorCode.PASSWORD_INCORRECT,
            http_status=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = AuthService.create_token_pair(user_ctx)

    # 将 Refresh Token 写入 HttpOnly Cookie
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=_settings.app.cookie_secure,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 天
    )

    return LoginResponse(code=0, success=True, message="登录成功", data=tokens)


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    使用 Refresh Token 换取新的 Token 对（Token 轮换机制）。
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise AuthError(
            "未提供 Refresh Token",
            errcode=ErrorCode.REFRESH_TOKEN_INVALID,
            http_status=401,
        )

    tokens = auth_service.refresh_access_token(refresh_token)
    if not tokens:
        raise AuthError(
            "Refresh Token 无效或已过期",
            errcode=ErrorCode.REFRESH_TOKEN_INVALID,
            http_status=401,
        )

    # Token 轮换：同时刷新 Refresh Token
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=_settings.app.cookie_secure,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )

    return LoginResponse(code=0, success=True, message="Token 刷新成功", data=tokens)


@router.post("/logout", response_model=CommonResponse, summary="用户登出")
async def logout(response: Response, user: UserContext = Depends(get_current_user)):
    """
    登出，清除 Refresh Token Cookie。
    """
    response.delete_cookie("refresh_token")
    return {"code": 0, "data": True, "message": "已登出"}


@router.get("/me", response_model=CommonResponse, summary="获取当前用户信息")
async def get_current_user_info(
    user: UserContext = Depends(get_current_user),
    rbac_service: RBACService = Depends(get_rbac_service),
):
    """
    获取当前登录用户信息。
    """
    if isinstance(user, str):
        return {
            "code": 0,
            "data": {
                "username": user,
                "user_id": 0,
                "level": 0,
                "permissions": [],
                "roles": [],
            },
        }
    roles = rbac_service.get_user_roles(user.user_id)
    user_detail = rbac_service.get_user_by_id(user.user_id)
    avatar = user_detail.AVATAR if user_detail else None
    email = user_detail.EMAIL if user_detail else None
    return {
        "code": 0,
        "data": {
            "user_id": user.user_id,
            "username": user.username,
            "nickname": user.nickname,
            "email": email,
            "avatar": avatar,
            "level": user.level,
            "permissions": user.permissions,
            # 超管按角色代码判定（角色代码不可通过接口修改）
            "is_superadmin": any(r.role_code == "superadmin" for r in roles) if roles else False,
            "is_default_password": rbac_service.is_default_password(user.user_id),
            "roles": [role.role_name for role in roles] if roles else [],
        },
    }
