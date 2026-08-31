"""领域枚举 — SyncType, SearchType, OsType, BrushDeleteType 等."""

from enum import Enum


class SyncType(Enum):
    MAN = "手动整理"
    MON = "目录同步"


class SearchType(Enum):
    WX = "微信"
    WEB = "WEB"
    DB = "豆瓣"
    SUBSCRIBE = "订阅"
    USERRSS = "自定义订阅"
    OT = "手动下载"
    TG = "Telegram"
    API = "第三方API请求"
    SLACK = "Slack"
    SYNOLOGY = "Synology Chat"
    PLUGIN = "插件"


class MatchMode(Enum):
    NORMAL = "正常模式"
    STRICT = "严格模式"


class IdentifyStatus(Enum):
    """批量识别结果状态"""

    HIT = "hit"
    NOT_FOUND = "not_found"
    ERROR = "error"


class OsType(Enum):
    WINDOWS = "Windows"
    LINUX = "Linux"
    SYNOLOGY = "Synology"
    MACOS = "MacOS"
    DOCKER = "Docker"


class BrushDeleteType(Enum):
    NOTDELETE = "不删除"
    SEEDTIME = "做种时间"
    RATIO = "分享率"
    UPLOADSIZE = "上传量"
    DLTIME = "下载耗时"
    AVGUPSPEED = "平均上传速度"
    IATIME = "未活动时间"
    PENDINGTIME = "等待时间"
    HRSEEDTIME = "H&R 做种时间"
    FREESPACE = "磁盘剩余空间"
    FREEEND = "Free 到期"
    FREESTATUS = "Free 状态"
    HR = "H&R 状态"
    ALIVETIME = "存活天数"
    UPSPEED = "当前上传速度"
    TRACKERERROR = "Tracker 错误"


class BrushStopType(Enum):
    FREEEND = "Free 到期"
    NOTSTOP = "不暂停"
    RATIO = "分享率"
    UPLOADSIZE = "上传量"
    SEEDTIME = "做种时间"
    AVGUPSPEED = "平均上传速度"


# 系统配置Key字典
class SystemConfigKey(Enum):
    # 同步媒体库范围
    SyncLibrary = "SyncLibrary"
    # 站点Cookie获取参数
    CookieUserInfo = "CookieUserInfo"
    # CookieCloud同步参数
    CookieCloud = "CookieCloud"
    # 默认下载器
    DefaultDownloader = "DefaultDownloader"
    # 默认下载设置
    DefaultDownloadSetting = "DefaultDownloadSetting"
    # 默认电影订阅设置
    DefaultSubscribeSettingMOV = "DefaultSubscribeSettingMOV"
    # 默认电视剧订阅设置
    DefaultSubscribeSettingTV = "DefaultSubscribeSettingTV"
    # 用户已安装的插件
    UserInstalledPlugins = "UserInstalledPlugins"
    # 已安装插件汇报状态
    UserInstalledPluginsReport = "UserInstalledPluginsReport"
    # 括削配置
    UserScraperConf = "UserScraperConf"
    # 索引站点
    UserIndexerSites = "UserIndexerSites"
    # 当前使用的搜索索引器
    SearchIndexer = "SearchIndexer"
    # 索引器配置（jackett/prowlarr）
    IndexerConfig = "IndexerConfig"
    # 是否启用内置索引器
    BuiltinIndexerEnabled = "BuiltinIndexerEnabled"
    # 是否启用Jackett索引器
    JackettIndexerEnabled = "JackettIndexerEnabled"
    # 是否启用Prowlarr索引器
    ProwlarrIndexerEnabled = "ProwlarrIndexerEnabled"


# 处理进度Key字典
class ProgressKey(Enum):
    # 搜索
    Search = "search"
    # RSS订阅搜索
    SubscribeSearch = "rsssearch"
    # 转移
    FileTransfer = "filetransfer"
    # 媒体库同步
    MediaSync = "mediasync"
    # 站点Cookie获取
    SiteCookie = "sitecookie"


class SubscribeType(Enum):
    # 手动
    Manual = "manual"
    # 自动
    Auto = "auto"


class SiteUseType(Enum):
    """站点用途标识（对应 CONFIG_SITE.INCLUDE 字段）."""

    RSS = "D"
    BRUSH = "S"
    STATISTIC = "T"


class UserRssTaskUseType(Enum):
    """自定义 RSS 任务用途."""

    DOWNLOAD = "D"
    SUBSCRIBE = "R"
    SEARCH = "S"


class SwitchState(Enum):
    """通用 Y/N 开关状态."""

    ON = "Y"
    OFF = "N"


def channel_name(channel) -> str:
    """将渠道标识规范化为展示名（与 SearchType.value 语义一致）"""
    return channel.value if isinstance(channel, SearchType) else (channel or "")


def channel_key(channel) -> str:
    """将渠道标识规范化为路由标识（与交互渠道 search_type 匹配，对应枚举名）"""
    return channel.name if isinstance(channel, SearchType) else (channel or "")
