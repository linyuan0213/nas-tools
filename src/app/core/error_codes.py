"""统一错误码注册表

编码规则（6 位以内整数，按业务域分段）：
    0       成功
    10xxx   通用/参数校验
    20xxx   认证与权限
    30xxx   媒体（识别、刮削、元数据）
    40xxx   下载（下载器、种子、任务）
    50xxx   站点 / 索引器 / RSS
    60xxx   订阅
    70xxx   插件
    80xxx   同步 / 刷流
    90xxx   系统 / 基础设施

每个错误码绑定：默认提示消息（面向用户）+ 默认 HTTP 状态码。
新增错误码时只需在 ErrorCode 与 _META 中各加一行。
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    SUCCESS = 0

    # 通用 10xxx
    UNKNOWN = 10000
    PARAM_VALIDATION_FAILED = 10001
    RESOURCE_NOT_FOUND = 10002
    RESOURCE_ALREADY_EXISTS = 10003
    OPERATION_FAILED = 10004
    RATE_LIMITED = 10005
    FILE_OPERATION_FAILED = 10006

    # 认证与权限 20xxx
    UNAUTHORIZED = 20001
    TOKEN_EXPIRED = 20002
    TOKEN_INVALID = 20003
    REFRESH_TOKEN_INVALID = 20004
    PERMISSION_DENIED = 20005
    USER_NOT_FOUND = 20006
    PASSWORD_INCORRECT = 20007
    APIKEY_NOT_FOUND = 20008
    APIKEY_INVALID = 20009

    # 媒体 30xxx
    MEDIA_RECOGNIZE_FAILED = 30001
    MEDIA_NOT_FOUND = 30002
    TMDB_REQUEST_FAILED = 30003
    DOUBAN_REQUEST_FAILED = 30004
    SCRAPE_FAILED = 30005
    IMAGE_FETCH_FAILED = 30006

    # 下载 40xxx
    DOWNLOADER_NOT_FOUND = 40001
    DOWNLOADER_CONNECT_FAILED = 40002
    TORRENT_ADD_FAILED = 40003
    TORRENT_NOT_FOUND = 40004
    DOWNLOAD_TASK_FAILED = 40005
    DOWNLOADER_SETTING_INVALID = 40006

    # 站点 / 索引器 / RSS 50xxx
    SITE_NOT_FOUND = 50001
    SITE_LOGIN_FAILED = 50002
    SITE_REQUEST_FAILED = 50003
    INDEXER_SEARCH_FAILED = 50004
    RSS_PARSE_FAILED = 50005

    # 订阅 60xxx
    SUBSCRIPTION_NOT_FOUND = 60001
    SUBSCRIPTION_ALREADY_EXISTS = 60002
    SUBSCRIPTION_FAILED = 60003

    # 插件 70xxx
    PLUGIN_NOT_FOUND = 70001
    PLUGIN_LOAD_FAILED = 70002
    PLUGIN_EXEC_FAILED = 70003
    PLUGIN_INSTALLING = 70004
    PLUGIN_NOT_INSTALLED = 70005
    PLUGIN_MANIFEST_INVALID = 70006
    PLUGIN_HOT_RELOAD_FAILED = 70007

    # 同步 / 刷流 80xxx
    SYNC_FAILED = 80001
    BRUSH_FAILED = 80002

    # 系统 / 基础设施 90xxx
    INTERNAL_ERROR = 90000
    DATABASE_ERROR = 90001
    CACHE_ERROR = 90002
    NETWORK_ERROR = 90003
    CONFIG_ERROR = 90004
    SCHEDULER_ERROR = 90005
    MESSAGE_SEND_FAILED = 90006
    STORAGE_ERROR = 90007
    MEDIA_SERVER_ERROR = 90008


# errcode -> (默认用户消息, 默认 HTTP 状态码)
_META: dict[ErrorCode, tuple[str, int]] = {
    ErrorCode.SUCCESS: ("成功", 200),
    ErrorCode.UNKNOWN: ("未知错误", 500),
    ErrorCode.PARAM_VALIDATION_FAILED: ("参数校验失败", 400),
    ErrorCode.RESOURCE_NOT_FOUND: ("资源不存在", 404),
    ErrorCode.RESOURCE_ALREADY_EXISTS: ("资源已存在", 409),
    ErrorCode.OPERATION_FAILED: ("操作失败", 500),
    ErrorCode.RATE_LIMITED: ("请求过于频繁，请稍后再试", 429),
    ErrorCode.FILE_OPERATION_FAILED: ("文件操作失败", 500),
    ErrorCode.UNAUTHORIZED: ("未认证或认证已过期", 401),
    ErrorCode.TOKEN_EXPIRED: ("登录已过期，请重新登录", 401),
    ErrorCode.TOKEN_INVALID: ("认证凭证无效", 401),
    ErrorCode.REFRESH_TOKEN_INVALID: ("Refresh Token 无效或已过期", 401),
    ErrorCode.PERMISSION_DENIED: ("权限不足", 403),
    ErrorCode.USER_NOT_FOUND: ("用户不存在", 404),
    ErrorCode.PASSWORD_INCORRECT: ("用户名或密码错误", 401),
    ErrorCode.APIKEY_NOT_FOUND: ("API Key 不存在", 404),
    ErrorCode.APIKEY_INVALID: ("API Key 无效", 401),
    ErrorCode.MEDIA_RECOGNIZE_FAILED: ("媒体识别失败", 500),
    ErrorCode.MEDIA_NOT_FOUND: ("未找到媒体信息", 404),
    ErrorCode.TMDB_REQUEST_FAILED: ("TMDB 请求失败", 502),
    ErrorCode.DOUBAN_REQUEST_FAILED: ("豆瓣请求失败", 502),
    ErrorCode.SCRAPE_FAILED: ("媒体刮削失败", 500),
    ErrorCode.IMAGE_FETCH_FAILED: ("图片获取失败", 404),
    ErrorCode.DOWNLOADER_NOT_FOUND: ("下载器不存在或未配置", 404),
    ErrorCode.DOWNLOADER_CONNECT_FAILED: ("下载器连接失败", 502),
    ErrorCode.TORRENT_ADD_FAILED: ("添加下载任务失败", 500),
    ErrorCode.TORRENT_NOT_FOUND: ("种子任务不存在", 404),
    ErrorCode.DOWNLOAD_TASK_FAILED: ("下载任务执行失败", 500),
    ErrorCode.DOWNLOADER_SETTING_INVALID: ("下载器配置无效", 400),
    ErrorCode.SITE_NOT_FOUND: ("站点不存在", 404),
    ErrorCode.SITE_LOGIN_FAILED: ("站点登录失败", 502),
    ErrorCode.SITE_REQUEST_FAILED: ("站点请求失败", 502),
    ErrorCode.INDEXER_SEARCH_FAILED: ("索引器搜索失败", 502),
    ErrorCode.RSS_PARSE_FAILED: ("RSS 解析失败", 500),
    ErrorCode.SUBSCRIPTION_NOT_FOUND: ("订阅不存在", 404),
    ErrorCode.SUBSCRIPTION_ALREADY_EXISTS: ("订阅已存在", 409),
    ErrorCode.SUBSCRIPTION_FAILED: ("订阅执行失败", 500),
    ErrorCode.PLUGIN_NOT_FOUND: ("插件不存在", 404),
    ErrorCode.PLUGIN_LOAD_FAILED: ("插件加载失败", 500),
    ErrorCode.PLUGIN_EXEC_FAILED: ("插件执行失败", 500),
    ErrorCode.PLUGIN_INSTALLING: ("插件正在安装中，请稍后再试", 409),
    ErrorCode.PLUGIN_NOT_INSTALLED: ("插件未安装", 404),
    ErrorCode.PLUGIN_MANIFEST_INVALID: ("插件清单无效", 400),
    ErrorCode.PLUGIN_HOT_RELOAD_FAILED: ("插件热重载失败", 500),
    ErrorCode.SYNC_FAILED: ("同步失败", 500),
    ErrorCode.BRUSH_FAILED: ("刷流任务执行失败", 500),
    ErrorCode.INTERNAL_ERROR: ("服务器内部错误", 500),
    ErrorCode.DATABASE_ERROR: ("数据库错误", 500),
    ErrorCode.CACHE_ERROR: ("缓存错误", 500),
    ErrorCode.NETWORK_ERROR: ("网络请求失败", 502),
    ErrorCode.CONFIG_ERROR: ("配置错误", 500),
    ErrorCode.SCHEDULER_ERROR: ("定时任务错误", 500),
    ErrorCode.MESSAGE_SEND_FAILED: ("消息推送失败", 502),
    ErrorCode.STORAGE_ERROR: ("存储后端错误", 502),
    ErrorCode.MEDIA_SERVER_ERROR: ("媒体服务器错误", 502),
}


def default_message(code: ErrorCode) -> str:
    return _META.get(code, _META[ErrorCode.UNKNOWN])[0]


def default_http_status(code: ErrorCode) -> int:
    return _META.get(code, _META[ErrorCode.UNKNOWN])[1]
