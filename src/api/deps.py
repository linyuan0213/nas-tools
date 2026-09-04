"""FastAPI 依赖注入."""

import uuid
from typing import Any, cast

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import log
from app.core.error_codes import ErrorCode
from app.core.exceptions import AuthError, PermissionDenied
from app.di.context import AppContext
from app.infrastructure.cache_system import TokenCache
from app.infrastructure.security import identify
from app.schemas.auth import UserContext
from app.services.apikey_service import APIKeyService
from app.services.auth_service import AuthService
from app.services.config_reloader import ConfigReloader
from app.services.config_service import ConfigService
from app.services.subscribe.management.calendar_service import SubscribeCalendarService
from app.services.subscribe.management.history_service import SubscribeHistoryService
from app.services.subscribe.management.service import SubscribeService
from app.services.system.config import ConfigUpdateService

# OAuth2 / Bearer 方案
bearer_scheme = HTTPBearer(auto_error=False)
bearer_scheme_dependency = Depends(bearer_scheme)


def get_app_context(request: Request) -> AppContext:
    """获取应用上下文 — 路由层访问对象图的唯一入口."""
    return request.app.state.context


def _extract_user_from_api_key(
    auth_header: str | None,
    query_key: str | None,
    apikey_service: APIKeyService,
    rbac_service,
) -> UserContext | None:
    """
    API Key 认证（支持 Header 和 Query 参数）
    使用 APIKeyService 验证 Key 并返回 UserContext
    """

    raw_key = None
    if auth_header:
        raw_key = str(auth_header).split()[-1]
    elif query_key:
        raw_key = query_key

    if not raw_key:
        return None

    api_key = apikey_service.validate_key(raw_key)
    if not api_key:
        return None

    # 记录使用日志（异步记录，不阻塞认证流程）
    try:
        apikey_service.record_usage(
            api_key_id=api_key.id,
            request_id=str(uuid.uuid4()),
            request_name="API 认证",
            status=1,
        )
    except Exception as e:  # noqa: BLE001
        log.debug(f"[API]忽略异常: {e}")

    # 查询创建用户的权限，API Key 继承创建者权限
    permissions = []
    level = 0
    username: str = "api_key"
    nickname = cast(str, api_key.name)
    created_by = api_key.created_by or 0

    if created_by:
        try:
            user = rbac_service.get_user_by_id(created_by)
            if user is not None:
                username = cast(str, getattr(user, "USERNAME", username) or username)
                nickname = cast(str, api_key.name)
                level = getattr(user, "LEVEL", 0) or 0
                try:
                    perms = rbac_service.get_user_permissions(created_by)
                    permissions = list(perms) if perms else []
                except Exception as e:  # noqa: BLE001
                    log.debug(f"[API]忽略异常: {e}")
        except Exception as e:  # noqa: BLE001
            log.debug(f"[API]忽略异常: {e}")

    return UserContext(
        user_id=created_by,
        username=username,
        nickname=nickname,
        level=level,
        permissions=permissions,
    )


def get_auth_service(app_context: AppContext = Depends(get_app_context)) -> AuthService:
    """获取认证服务实例"""
    return AuthService(rbac_service=app_context.rbac_service)


def get_current_user(
    request: Request,
    app_context: AppContext = Depends(get_app_context),
    credentials: HTTPAuthorizationCredentials | None = bearer_scheme_dependency,
) -> UserContext:
    """
    统一认证依赖：优先 JWT，兼容旧 Token(Bearer)、API Key。
    返回 UserContext；认证失败时抛出 401。
    """
    auth_header: str | None = credentials.credentials if credentials else None

    # 1) JWT 认证（新标准）
    user_ctx = _extract_user_from_jwt(auth_header)
    if user_ctx:
        return user_ctx

    # 2) 旧 Token 认证（APIv1 兼容）
    username = _extract_user_from_token(auth_header)
    if username:
        return UserContext(user_id=0, username=username, level=0, permissions=[])

    # 3) API Key 认证
    query_key = request.query_params.get("apikey")
    user_ctx = _extract_user_from_api_key(
        auth_header,
        query_key,
        apikey_service=app_context.apikey_service,
        rbac_service=app_context.rbac_service,
    )
    if user_ctx:
        return user_ctx

    raise AuthError(
        "安全认证未通过，请检查登录状态、Token 或 ApiKey",
        errcode=ErrorCode.UNAUTHORIZED,
        http_status=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_optional(
    request: Request,
    app_context: AppContext = Depends(get_app_context),
    credentials: HTTPAuthorizationCredentials | None = bearer_scheme_dependency,
) -> UserContext | None:
    """
    可选认证：未登录返回 None，不抛异常。
    """
    try:
        return get_current_user(request, app_context, credentials)
    except AuthError as e:
        # 仅将"未认证"视为可选；权限不足(403)不属于可选场景，需继续抛出
        if isinstance(e, PermissionDenied):
            raise
        return None


current_user_dependency = Depends(get_current_user)


def require_permission(permission: str):
    """
    权限检查装饰器工厂
    用法: user = Depends(require_permission("download:read"))
    """

    def checker(user: UserContext = current_user_dependency) -> UserContext:
        if permission not in user.permissions:
            raise PermissionDenied(f"权限不足: {permission}")
        return user

    return checker


def require_any_permission(*permissions: str):
    """
    权限检查装饰器工厂（满足任一权限即可）
    用法: user = Depends(require_any_permission("download:view", "download:manage"))
    """

    def checker(user: UserContext = current_user_dependency) -> UserContext:
        if any(p in user.permissions for p in permissions):
            return user
        raise PermissionDenied(f"权限不足，需要以下任一权限: {', '.join(permissions)}")

    return checker


def require_all_permissions(*permissions: str):
    """
    权限检查装饰器工厂（需满足所有权限）
    用法: user = Depends(require_all_permissions("user:view", "user:update"))
    """

    def checker(user: UserContext = current_user_dependency) -> UserContext:
        missing = [p for p in permissions if p not in user.permissions]
        if missing:
            raise PermissionDenied(f"权限不足，缺少: {', '.join(missing)}")
        return user

    return checker


def get_config_service(app_context: AppContext = Depends(get_app_context)) -> ConfigService:
    """获取配置服务实例"""
    return app_context.config_service


def get_message_service(app_context: AppContext = Depends(get_app_context)):
    """获取消息客户端服务实例"""
    return app_context.message_client_service


def get_message(app_context: AppContext = Depends(get_app_context)):
    """获取消息门面实例"""
    return app_context.message


# --- 领域 Service 工厂 ---


def get_download_service(app_context: AppContext = Depends(get_app_context)):
    """获取下载服务实例"""
    return app_context.download_service


def get_site_service(app_context: AppContext = Depends(get_app_context)):
    """获取站点服务实例"""
    return app_context.site_service


def get_indexer_service(app_context: AppContext = Depends(get_app_context)):
    """获取索引器服务实例"""
    return app_context.indexer_service


def get_media_info_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体信息服务实例"""
    return app_context.media_info_service


def get_media_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体服务实例"""
    return app_context.media_service


def get_subscribe_service(app_context: AppContext = Depends(get_app_context)) -> SubscribeService:
    """获取订阅服务实例"""
    return app_context.subscribe_service


def get_sync_service(app_context: AppContext = Depends(get_app_context)):
    """获取同步服务实例"""
    return app_context.sync_service


def get_subscribe_history_service(app_context: AppContext = Depends(get_app_context)) -> SubscribeHistoryService:
    """获取订阅历史服务实例"""
    return app_context.subscribe_history_service


def get_subscribe_calendar_service(app_context: AppContext = Depends(get_app_context)) -> SubscribeCalendarService:
    """获取订阅日历服务实例"""
    return app_context.subscribe_calendar_service


def get_words_service(app_context: AppContext = Depends(get_app_context)):
    """获取自定义识别词服务实例"""
    return app_context.words_service


def get_user_rss_service(app_context: AppContext = Depends(get_app_context)):
    """获取用户 RSS 服务实例"""
    return app_context.user_rss_service


def get_scheduler_service(app_context: AppContext = Depends(get_app_context)):
    """获取调度器服务实例"""
    return app_context.scheduler_service


def get_system_scheduler_service(app_context: AppContext = Depends(get_app_context)):
    """获取系统调度器服务实例（用于启动后台服务）"""
    return app_context.scheduler_core


def get_filter_service(app_context: AppContext = Depends(get_app_context)):
    """获取过滤服务实例"""
    return app_context.filter_service


def get_net_test_service(app_context: AppContext = Depends(get_app_context)):
    """获取网络测试服务实例"""
    return app_context.net_test_service


def get_apikey_service(app_context: AppContext = Depends(get_app_context)):
    """获取 API Key 服务实例"""
    return app_context.apikey_service


def get_system_config_service(app_context: AppContext = Depends(get_app_context)):
    """获取系统配置服务实例"""
    return app_context.system_config_service


def get_config_update_service():
    """获取配置更新服务实例"""
    return ConfigUpdateService()


def get_user_manage_service(app_context: AppContext = Depends(get_app_context)):
    """获取用户管理服务实例"""
    return app_context.user_manage_service


def get_progress_service(app_context: AppContext = Depends(get_app_context)):
    """获取进度服务实例"""
    return app_context.progress_service


def get_message_sender_service(app_context: AppContext = Depends(get_app_context)):
    """获取消息发送服务实例"""
    return app_context.message_sender_service


def get_system_info_service(app_context: AppContext = Depends(get_app_context)):
    """获取系统信息服务实例"""
    return app_context.system_info_service


def get_system_lifecycle_service(app_context: AppContext = Depends(get_app_context)):
    """获取系统生命周期服务实例"""
    return app_context.system_lifecycle


def get_backup_restore_service(app_context: AppContext = Depends(get_app_context)):
    """获取备份恢复服务实例"""
    return app_context.backup_restore_service


def get_indexer_config_service(app_context: AppContext = Depends(get_app_context)):
    """获取索引器配置服务实例"""
    return app_context.indexer_config_service


def get_media_server_config_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体服务器配置服务实例"""
    return app_context.media_server_config_service


def get_web_search_service(app_context: AppContext = Depends(get_app_context)):
    """获取 Web 搜索服务实例"""
    return app_context.web_search_service


def get_downloader_service(app_context: AppContext = Depends(get_app_context)):
    """获取下载器核心服务实例"""
    return app_context.downloader_core


def get_filetransfer_service(app_context: AppContext = Depends(get_app_context)):
    """获取文件转移服务实例"""
    return app_context.filetransfer_service


def get_media_recommendation_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体推荐服务实例"""
    return app_context.media_recommendation_service


def get_searcher_service(app_context: AppContext = Depends(get_app_context)):
    """获取搜索服务实例"""
    return app_context.searcher


def get_tmdb_blacklist_service(app_context: AppContext = Depends(get_app_context)):
    """获取 TMDB 黑名单服务实例"""
    return app_context.tmdb_blacklist_service


def get_thread_executor(app_context: AppContext = Depends(get_app_context)):
    """获取线程助手实例"""
    return app_context.thread_executor


def get_media_config_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体库路径配置服务"""
    return app_context.media_config_service


def get_storage_backend_service(app_context: AppContext = Depends(get_app_context)):
    """获取存储后端服务实例"""
    return app_context.storage_backend_service


def get_rbac_service(app_context: AppContext = Depends(get_app_context)):
    """获取 RBAC 服务实例"""
    return app_context.rbac_service


def get_subscription_monitor(app_context: AppContext = Depends(get_app_context)):
    """获取订阅监控实例"""
    return app_context.subscription_monitor


def get_hook_system(app_context: AppContext = Depends(get_app_context)):
    """获取 Hook 系统实例"""
    return app_context.hook_system


def get_plugin_framework_service(app_context: AppContext = Depends(get_app_context)):
    """获取插件框架服务实例"""
    return app_context.plugin_framework_service


def get_plugin_market_service(app_context: AppContext = Depends(get_app_context)):
    """获取插件市场服务实例"""
    return app_context.plugin_market_service


def get_brush_service(app_context: AppContext = Depends(get_app_context)):
    """获取刷流服务实例"""
    return app_context.brush_service


def get_file_index_service(app_context: AppContext = Depends(get_app_context)):
    """获取文件索引服务实例"""
    return app_context.file_index_service


def get_media_file_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体文件服务实例"""
    return app_context.media_file_service


def get_media_library_service(app_context: AppContext = Depends(get_app_context)):
    """获取媒体库服务实例"""
    return app_context.media_library_service


def get_search_result_service(app_context: AppContext = Depends(get_app_context)):
    """获取搜索结果服务实例"""
    return app_context.search_result_service


def get_transfer_history_service(app_context: AppContext = Depends(get_app_context)):
    """获取转移历史服务实例"""
    return app_context.transfer_history_service


def get_config_reloader(app_context: AppContext = Depends(get_app_context)):
    """获取配置重载器实例"""
    return ConfigReloader(context=app_context)


# --- 兼容旧 Registry 获取方式（逐步废弃）---


def _get_legacy_service(name: str) -> Any:
    """通用服务工厂 — 已废弃，仅保留签名兼容。"""
    raise RuntimeError(f"Registry 已移除，请改用 AppContext.{name}")


def _extract_user_from_token(auth_header: str | None) -> str | None:
    """
    Token 认证（APIv1 ClientResource / Bearer）
    """
    if not auth_header:
        return None
    latest_token = TokenCache.get(auth_header)
    if not latest_token:
        return None
    flag, username = identify(latest_token)
    if not username:
        return None
    if not flag:
        return None
    return username


def _extract_user_from_jwt(auth_header: str | None) -> UserContext | None:
    """
    JWT 认证：从 Authorization header 提取并验证 JWT Token
    """
    if not auth_header:
        return None
    # 支持 "Bearer xxx" 或直接 "xxx"
    token = auth_header.split()[-1] if " " in auth_header else auth_header
    return AuthService.verify_token(token)


def get_retriever(app_context: AppContext = Depends(get_app_context)):
    """获取 RAG 检索器（agent 未启用时为 None）"""
    return app_context.retriever


def get_knowledge_ingestor(app_context: AppContext = Depends(get_app_context)):
    """获取知识库采集器（agent 未启用时为 None）"""
    return app_context.knowledge_ingestor
