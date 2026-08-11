"""
Nexus Media 统一异常体系

层次结构：
    NexusError (基类)
    ├── DomainError          领域/业务逻辑异常
    │   ├── MediaError       媒体识别、刮削相关
    │   ├── BrushError       刷流任务相关
    │   ├── SubscribeError   订阅相关
    │   └── SyncError        同步相关
    ├── RepositoryError      数据仓储异常
    │   ├── DatabaseError    数据库连接/查询失败
    │   └── CacheError       缓存操作失败
    ├── ServiceError         服务层异常
    │   ├── AuthError        认证/授权失败
    │   ├── ConfigError      配置读取/校验失败
    │   └── SchedulerError   定时任务异常
    ├── InfrastructureError  基础设施/外部服务异常
    │   ├── NetworkError     网络请求失败
    │   ├── DownloadError    下载器通信失败
    │   ├── IndexerError     索引器/站点访问失败
    │   ├── MessageError     消息推送失败
    │   └── TMDBError        TMDB API 错误 (兼容旧类)
    └── ValidationError      输入参数校验失败

使用约定：
- 捕获时优先捕获具体异常类型，避免裸 `except Exception`。
- 如需统一兜底，捕获 `NexusError` 而非 `Exception`。
- 异常消息应包含足够上下文，便于排查。
"""

from __future__ import annotations

from app.core.error_codes import ErrorCode, default_http_status, default_message


class NexusError(Exception):
    """应用根异常

    - errcode: 业务错误码（ErrorCode），用于前后端统一识别
    - http_status: 建议的 HTTP 状态码，默认取自错误码注册表
    - code: 兼容旧的字符串标识（类名）
    """

    errcode: ErrorCode = ErrorCode.UNKNOWN

    def __init__(
        self,
        message: str = "",
        *,
        errcode: ErrorCode | None = None,
        http_status: int | None = None,
        headers: dict[str, str] | None = None,
        code: str | None = None,
        details: dict | None = None,
    ):
        self.errcode = errcode or self.__class__.errcode
        self.http_status = http_status or default_http_status(self.errcode)
        self.headers = headers or {}
        self.message = message or default_message(self.errcode)
        super().__init__(self.message)
        self.code = code or self._default_code()
        self.details = details or {}

    def _default_code(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} | details={self.details}"
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict:
        return {
            "errcode": int(self.errcode),
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ------------------------------------------------------------------
# Domain 层
# ------------------------------------------------------------------


class DomainError(NexusError):
    """领域逻辑异常"""


class MediaError(DomainError):
    """媒体识别、刮削、元数据异常"""

    errcode = ErrorCode.MEDIA_RECOGNIZE_FAILED


class BrushError(DomainError):
    """刷流任务规则/执行异常"""

    errcode = ErrorCode.BRUSH_FAILED


class SubscribeError(DomainError):
    """RSS/订阅异常"""

    errcode = ErrorCode.SUBSCRIPTION_FAILED


class ResourceNotFoundError(DomainError):
    """资源不存在（实体未找到）"""

    errcode = ErrorCode.RESOURCE_NOT_FOUND


class ResourceAlreadyExistsError(DomainError):
    """资源已存在（唯一键冲突）"""

    errcode = ErrorCode.RESOURCE_ALREADY_EXISTS


class SyncError(DomainError):
    """媒体库同步异常"""

    errcode = ErrorCode.SYNC_FAILED


# ------------------------------------------------------------------
# Repository 层
# ------------------------------------------------------------------


class RepositoryError(NexusError):
    """数据仓储异常"""


class DatabaseError(RepositoryError):
    """数据库连接/查询/写入失败"""

    errcode = ErrorCode.DATABASE_ERROR


class CacheError(RepositoryError):
    """缓存读写失败"""

    errcode = ErrorCode.CACHE_ERROR


class MigrationError(RepositoryError):
    """数据库迁移失败"""

    errcode = ErrorCode.DATABASE_ERROR


# ------------------------------------------------------------------
# Service 层
# ------------------------------------------------------------------


class ServiceError(NexusError):
    """服务层异常"""


class AuthError(ServiceError):
    """认证或授权失败"""

    errcode = ErrorCode.UNAUTHORIZED


class PermissionDenied(AuthError):
    """权限不足"""

    errcode = ErrorCode.PERMISSION_DENIED


class ConfigError(ServiceError):
    """配置读取、校验、迁移失败"""

    errcode = ErrorCode.CONFIG_ERROR


class SchedulerError(ServiceError):
    """定时任务调度异常"""

    errcode = ErrorCode.SCHEDULER_ERROR


# ------------------------------------------------------------------
# Infrastructure 层
# ------------------------------------------------------------------


class InfrastructureError(NexusError):
    """基础设施/外部服务异常"""


class NetworkError(InfrastructureError):
    """通用网络请求失败"""

    errcode = ErrorCode.NETWORK_ERROR


class DownloadError(InfrastructureError):
    """下载器客户端通信/操作失败"""

    errcode = ErrorCode.DOWNLOADER_CONNECT_FAILED


class IndexerError(InfrastructureError):
    """索引器/站点访问失败"""

    errcode = ErrorCode.INDEXER_SEARCH_FAILED


class MessageError(InfrastructureError):
    """消息推送渠道异常"""

    errcode = ErrorCode.MESSAGE_SEND_FAILED


class MediaServerError(InfrastructureError):
    """媒体服务器(Emby/Jellyfin/Plex)通信失败"""

    errcode = ErrorCode.MEDIA_SERVER_ERROR


class StorageError(InfrastructureError):
    """存储后端(S3/SMB/WebDAV等)操作失败"""

    errcode = ErrorCode.STORAGE_ERROR


class PluginError(InfrastructureError):
    """插件加载/执行失败"""

    errcode = ErrorCode.PLUGIN_EXEC_FAILED


class PluginNotInstalledError(PluginError):
    """插件未安装"""

    errcode = ErrorCode.PLUGIN_NOT_INSTALLED


class PluginInstallingError(PluginError):
    """插件正在安装中"""

    errcode = ErrorCode.PLUGIN_INSTALLING


class PluginManifestInvalidError(PluginError):
    """插件清单无效"""

    errcode = ErrorCode.PLUGIN_MANIFEST_INVALID


class PluginHotReloadError(PluginError):
    """插件热重载失败"""

    errcode = ErrorCode.PLUGIN_HOT_RELOAD_FAILED


# ------------------------------------------------------------------
# Validation 层
# ------------------------------------------------------------------


class ValidationError(NexusError):
    """输入参数校验失败"""

    errcode = ErrorCode.PARAM_VALIDATION_FAILED


class MissingFieldError(ValidationError):
    """缺少必填字段"""

    errcode = ErrorCode.PARAM_VALIDATION_FAILED


class InvalidValueError(ValidationError):
    """字段值非法"""

    errcode = ErrorCode.PARAM_VALIDATION_FAILED


# ------------------------------------------------------------------
# 兼容旧 TMDBError（保留同名，改继承链）
# ------------------------------------------------------------------


class TMDBError(InfrastructureError):
    """TMDB API 调用失败（兼容旧类，继承链已改为 InfrastructureError）"""

    errcode = ErrorCode.TMDB_REQUEST_FAILED
