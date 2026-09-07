"""
数据库模型模块

此模块包含所有数据库模型定义，按业务域拆分为多个子模块。
"""

# 基础定义
# API Key 模型
# Agent 记忆模型
from app.db.models.agent_memory import (
    AGENTCONVERSATION,
    AGENTMESSAGE,
    AGENTWEBMESSAGE,
)
from app.db.models.apikey import (
    APIKEY,
    APIKEYLOG,
)
from app.db.models.base import Base, BaseMedia

# 刷流相关模型
from app.db.models.brush import (
    BRUSHEVENTLOG,
    SITEBRUSHRULE,
    SITEBRUSHTASK,
    SITEBRUSHTORRENTS,
)

# 配置相关模型
from app.db.models.config import (
    CONFIGCATEGORY,
    CONFIGCATEGORYRULE,
    CONFIGFILTERGROUP,
    CONFIGFILTERRULES,
    CONFIGMEDIA,
    CONFIGRSSPARSER,
    CONFIGSITE,
    CONFIGSYNCPATHS,
    CONFIGUSERRSS,
    CONFIGUSERS,
    MEDIASERVER,
)

# 分布式锁模型
from app.db.models.distributed_lock import (
    DISTRIBUTEDLOCK,
)

# 下载相关模型
from app.db.models.download import (
    DOWNLOADER,
    DOWNLOADHISTORY,
    DOWNLOADSETTING,
)

# 索引器统计模型
from app.db.models.indexer import (
    INDEXERCONFIG,
    INDEXERSITECONFIG,
    INDEXERSTATISTICS,
)

# 媒体同步模型
from app.db.models.media_sync import (
    MEDIASYNCITEMS,
    MEDIASYNCSTATISTIC,
)

# 消息相关模型
from app.db.models.message import (
    MESSAGECLIENT,
)

# 插件历史和TMDB黑名单模型
from app.db.models.plugin import (
    PLUGINCONFIG,
    PLUGINHISTORY,
    PLUGINHOOKS,
    PLUGINLOGS,
    PLUGINMANIFEST,
    PLUGINMARKETSOURCE,
    TMDBBLACKLIST,
    TORRENTREMOVETASK,
    USERRSSTASKHISTORY,
)

# Web Push 订阅
from app.db.models.push_subscription import PushSubscription

# RBAC权限管理模型
from app.db.models.rbac import (
    RBACMenu,
    RBACOperationLog,
    RBACPermission,
    RBACRole,
    RBACUser,
    RBACUserLoginLog,
)

# 搜索结果模型
from app.db.models.search import (
    SEARCHRESULTINFO,
)

# 站点统计模型
from app.db.models.site import (
    SITEFAVICON,
    SITESTATISTICSHISTORY,
    SITEUSERINFOSTATS,
    SITEUSERSEEDINGINFO,
)

# 站点解析健康度
from app.db.models.site_parse_health import SiteParseHealth

# 存储后端模型
from app.db.models.storage_backend import (
    STORAGEBACKEND,
)

# RSS相关模型
from app.db.models.subscribe import (
    SubscribeHistory,
    SubscribeMovies,
    SubscribeTorrents,
    SubscribeTvEpisodes,
    SubscribeTvs,
)

# 同步历史模型
from app.db.models.sync import (
    SYNCHISTORY,
)

# 系统字典模型
from app.db.models.system import (
    SYSTEMDICT,
)

# 转移相关模型
from app.db.models.transfer import (
    TRANSFERBLACKLIST,
    TRANSFERHISTORY,
    TRANSFERUNKNOWN,
)

# 自定义识别词模型
from app.db.models.word import (
    CUSTOMWORDGROUPS,
    CUSTOMWORDS,
)

__all__ = [
    # 基础
    "Base",
    "BaseMedia",
    # 配置
    "CONFIGFILTERGROUP",
    "CONFIGFILTERRULES",
    "CONFIGRSSPARSER",
    "CONFIGSITE",
    "CONFIGSYNCPATHS",
    "CONFIGUSERS",
    "CONFIGUSERRSS",
    "MEDIASERVER",
    "CONFIGMEDIA",
    "CONFIGCATEGORY",
    "CONFIGCATEGORYRULE",
    "STORAGEBACKEND",
    # 识别词
    "CUSTOMWORDS",
    "CUSTOMWORDGROUPS",
    # 站点解析健康度
    "SiteParseHealth",
    # Web Push 订阅
    "PushSubscription",
    # 下载
    "DOWNLOADER",
    "DOWNLOADHISTORY",
    "DOWNLOADSETTING",
    # 消息
    "MESSAGECLIENT",
    # RSS
    "SubscribeHistory",
    "SubscribeMovies",
    "SubscribeTorrents",
    "SubscribeTvs",
    "SubscribeTvEpisodes",
    # 刷流
    "BRUSHEVENTLOG",
    "SITEBRUSHRULE",
    "SITEBRUSHTASK",
    "SITEBRUSHTORRENTS",
    # 站点统计
    "SITESTATISTICSHISTORY",
    "SITEUSERINFOSTATS",
    "SITEFAVICON",
    "SITEUSERSEEDINGINFO",
    # 转移
    "TRANSFERBLACKLIST",
    "TRANSFERHISTORY",
    "TRANSFERUNKNOWN",
    # 索引器
    "INDEXERCONFIG",
    "INDEXERSTATISTICS",
    "INDEXERSITECONFIG",
    # 插件
    "PLUGINHISTORY",
    "TMDBBLACKLIST",
    "TORRENTREMOVETASK",
    "USERRSSTASKHISTORY",
    "PLUGINMANIFEST",
    "PLUGINCONFIG",
    "PLUGINLOGS",
    "PLUGINHOOKS",
    # 媒体同步
    "MEDIASYNCITEMS",
    "MEDIASYNCSTATISTIC",
    # 搜索
    "SEARCHRESULTINFO",
    # 同步
    "SYNCHISTORY",
    # 系统
    "SYSTEMDICT",
    # RBAC权限管理
    "RBACUser",
    "RBACRole",
    "RBACPermission",
    "RBACMenu",
    "RBACUserLoginLog",
    "RBACOperationLog",
    # API Key
    "APIKEY",
    "AGENTCONVERSATION",
    "AGENTMESSAGE",
    "AGENTWEBMESSAGE",
    "APIKEYLOG",
    # 分布式锁
    "DISTRIBUTEDLOCK",
]
