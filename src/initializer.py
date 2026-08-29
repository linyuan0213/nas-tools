import os

import log
from app.core.root_path import get_script_path
from app.core.settings import settings
from app.core.system_config import SystemConfig
from app.db.repositories.apikey_repo_adapter import APIKeyLogRepositoryAdapter, APIKeyRepositoryAdapter
from app.db.repositories.config_repo_adapter import FilterGroupRepositoryAdapter
from app.db.repositories.indexer_site_config_repo_adapter import IndexerSiteConfigRepositoryAdapter
from app.db.repositories.site_repo_adapter import SiteRepositoryAdapter
from app.db.repositories.subscribe_repository import SubscribeRepository
from app.db.sql_adapter import adapt_sql_for_engine
from app.domain.enums import SystemConfigKey
from app.infrastructure.cache_system.events import init_event_bridge
from app.infrastructure.redis import RedisStore
from app.services.apikey_service import APIKeyService
from app.services.category_init import CategoryInitializer
from app.services.rbac_init import init_admin_user
from app.services.rbac_init import init_rbac_system as rbac_init
from app.utils import ExceptionUtils


def init_default_filters():
    """启动时从 init_filter.sql 导入/补齐默认过滤规则（幂等：INSERT OR IGNORE 仅补新规则，不覆盖已有）"""
    sql_file = os.path.join(get_script_path(), "init_filter.sql")
    if not os.path.exists(sql_file):
        return
    try:
        repo = FilterGroupRepositoryAdapter()
        with open(sql_file, encoding="utf-8") as f:
            for stmt in f.read().split(";\n"):
                stmt = stmt.strip()
                if stmt and "INSERT" in stmt.upper():
                    repo._repo._execute_raw(adapt_sql_for_engine(stmt))
        log.info("[Initialize]默认过滤规则初始化完成")
    except Exception as e:
        log.error(f"[Initialize]默认过滤规则初始化失败: {e!s}")
        ExceptionUtils.exception_traceback(e)


def init_default_categories():
    """初始化默认分类配置（从 YAML 模板导入数据库）"""
    try:
        CategoryInitializer().run()
    except Exception as e:
        log.error(f"[Initialize]默认分类配置初始化失败: {e!s}")
        ExceptionUtils.exception_traceback(e)


def check_config():
    """
    检查配置文件，如有错误进行日志输出
    """
    # 检查日志输出
    _log_cfg = settings.get("log")
    if _log_cfg:
        logtype = _log_cfg.get("type")
        if logtype:
            log.info(f"日志输出类型为：{logtype}")
        if logtype == "file":
            logpath = _log_cfg.get("path")
            if not logpath:
                log.warn("[Config]日志文件路径未配置，将使用默认路径")
            else:
                log.info(f"日志将写入文件：{logpath}")
    else:
        log.error("[Config]配置文件格式错误，找不到log配置项！")

    # 检测系统设置
    _app_cfg = settings.get("app")
    if _app_cfg:
        # 检查WEB端口
        web_port = _app_cfg.get("web_port")
        if not web_port:
            log.warn("[Config]WEB服务端口未设置，将使用默认3000端口")

        # 检查登录用户和密码
        login_user = _app_cfg.get("login_user")
        login_password = _app_cfg.get("login_password")
        if not login_user or not login_password:
            log.warn("[Config]WEB管理用户或密码未设置，将使用默认用户：admin，密码：password")
        else:
            log.info(f"WEB管理页面用户：{login_user!s}")

        # 检查HTTPS
        ssl_cert = _app_cfg.get("ssl_cert")
        ssl_key = _app_cfg.get("ssl_key")
        if os.environ.get("NEXUS_PORT"):
            web_port = os.environ.get("NEXUS_PORT")
        if not ssl_cert or not ssl_key:
            log.info(f"未启用https，请使用 http://IP:{web_port!s} 访问管理页面")
        else:
            if not os.path.exists(ssl_cert):
                log.warn(f"[Config]ssl_cert文件不存在：{ssl_cert}")
            if not os.path.exists(ssl_key):
                log.warn(f"[Config]ssl_key文件不存在：{ssl_key}")
            log.info(f"已启用https，请使用 https://IP:{web_port!s} 访问管理页面")
    else:
        log.error("[Config]配置文件格式错误，找不到app配置项！")


def update_config(indexer_statistics_repo=None):
    """
    升级配置文件
    """
    _config = settings.get()
    overwrite_config = False

    # security.api_key 已废弃：
    # - JWT 签名改用 get_secret_key()（从 security.jwt_secret 或 app.web_secret_key 获取）
    # - Webhook 验证改用数据库管理的 API Key（APIKeyService）
    # 保留此段代码用于清理旧配置项（可选）
    _security_cfg = _config.get("security", {})
    if _security_cfg.get("api_key"):
        _config["security"].pop("api_key", None)
        overwrite_config = True

    # 日志配置迁移：从 app.xxx 迁移到 log.xxx
    try:
        app_config = _config.get("app", {})
        # 定义：{旧键: 新键}
        log_mapping = {"logtype": "type", "loglevel": "level", "logpath": "path"}

        # 初始化 log 节点（如果不存在）
        if "log" not in _config:
            _config["log"] = {}

        migrated = False
        for old_key, new_key in log_mapping.items():
            if old_key in app_config:
                # 1. 迁移数据到新位置
                _config["log"][new_key] = app_config.get(old_key)
                # 2. 删除旧位置的数据
                app_config.pop(old_key)
                migrated = True
                log.info(f"[Config]日志配置已迁移：app.{old_key} -> log.{new_key}，并已移除旧配置。")

        # 日志路径迁移：config/logs -> data/logs
        _log_path = _config.get("log", {}).get("path") or ""
        if isinstance(_log_path, str) and "config/logs" in _log_path.replace("\\", "/"):
            _new_path = _log_path.replace("config/logs", "data/logs")
            _config["log"]["path"] = _new_path
            migrated = True
            log.info(f"[Config]日志路径已迁移：{_log_path} -> {_new_path}")

        if migrated:
            overwrite_config = True
    except Exception as e:
        ExceptionUtils.exception_traceback(e)

    # 站点数据刷新时间默认配置
    try:
        if "ptrefresh_date_cron" not in _config.get("pt", {}):
            _config.setdefault("pt", {})
            _config["pt"]["ptrefresh_date_cron"] = "00:05"
            overwrite_config = True
    except Exception as e:
        ExceptionUtils.exception_traceback(e)

    # TMDB代理服务开关迁移（已废弃，不再硬编码代理域名）
    try:
        _lab_cfg = _config.get("laboratory", {})
        if _lab_cfg.get("tmdb_proxy"):
            _config["laboratory"].pop("tmdb_proxy", None)
            overwrite_config = True
    except Exception as e:
        ExceptionUtils.exception_traceback(e)

    # 重写配置文件
    if overwrite_config:
        settings.save(_config)


def check_redis():
    """检查 Redis 状态，仅记录日志，不阻塞启动"""

    try:
        redis_store = RedisStore()
        if redis_store.is_available():
            log.info("Redis 正在运行...")
        else:
            log.info("Redis 未启用，使用内存缓存...")
    except Exception as e:
        log.info(f"Redis 未启用，使用内存缓存: {e}")


def init_message_webhook_apikey(apikey_service=None):
    """
    初始化消息通知 Webhook 的系统级 API Key
    在 API_KEYS 表中创建/获取名为 MessageWebhook 的系统 key
    """
    try:
        if apikey_service is None:
            apikey_service = APIKeyService(
                key_repo=APIKeyRepositoryAdapter(),
                log_repo=APIKeyLogRepositoryAdapter(),
            )
        apikey_service.get_or_create_system_key("MessageWebhook")
        log.info("[Initialize]消息 Webhook API Key 已就绪")
    except Exception as e:
        log.error(f"[Initialize]消息 Webhook API Key 初始化失败：{e!s}")
        ExceptionUtils.exception_traceback(e)


def init_indexer_site_config():
    """
    从旧的 UserIndexerSites（CONFIG_SITE.ID 列表）迁移到 INDEXER_SITE_CONFIG 表。
    仅执行一次，通过 SystemConfig 标记避免重复迁移。
    """
    try:
        system_config = SystemConfig()
        migration_done = system_config.get("IndexerSiteConfigMigrated")
        if migration_done:
            return

        user_indexer_sites = system_config.get(SystemConfigKey.UserIndexerSites) or []
        if not isinstance(user_indexer_sites, list):
            user_indexer_sites = []
        site_repo = SiteRepositoryAdapter()
        sites = site_repo.list_all()
        site_name_by_id = {site.id: site.name for site in sites}

        adapter = IndexerSiteConfigRepositoryAdapter()
        adapter.migrate_from_user_indexer_sites(user_indexer_sites, site_name_by_id)

        system_config.set("IndexerSiteConfigMigrated", "1")
        log.info(f"[Initialize]索引器站点配置迁移完成，共 {len(site_name_by_id)} 个站点")
    except Exception as e:
        log.error(f"[Initialize]索引器站点配置迁移失败: {e!s}")
        ExceptionUtils.exception_traceback(e)


def update_rss_state():
    """
    初始化时批量重置搜索中(S)的订阅为待处理(D)
    由 SubscriptionMonitor 自动重新启动队列搜索
    """
    try:
        SubscribeRepository().reset_rss_state()
        log.info("[Initialize]搜索中订阅已重置为待处理")
    except Exception as e:
        log.error(f"[Initialize]重置订阅状态失败：{e!s}")
        ExceptionUtils.exception_traceback(e)


def init_event_handlers(event_bus=None, hook_system=None):
    """初始化事件桥接（handler 已在 build_infrastructure 中注册）。"""
    try:
        if event_bus is not None:
            init_event_bridge(event_bus)
        log.info("[Initialize]事件桥接已初始化")
    except Exception as e:
        log.error(f"[Initialize]事件桥接初始化失败：{e!s}")
        ExceptionUtils.exception_traceback(e)


def init_rbac_system():
    """
    初始化 RBAC 权限管理系统
    - 初始化默认权限、菜单、角色
    - 创建管理员用户
    """
    try:
        # 初始化 RBAC 基础数据
        rbac_init()

        # 获取配置中的管理员账号
        _app_cfg = settings.get("app")
        login_user = _app_cfg.get("login_user") or "admin"
        login_password = _app_cfg.get("login_password") or "password"

        # 如果是哈希密码，使用原始密码
        if login_password.startswith("[hash]"):
            login_password = "password"

        # 创建管理员用户
        init_admin_user(login_user, login_password)
        log.info(f"[Initialize]RBAC 系统初始化完成，管理员: {login_user}")

    except Exception as e:
        log.error(f"[Initialize]RBAC 系统初始化失败: {e!s}")
        ExceptionUtils.exception_traceback(e)
