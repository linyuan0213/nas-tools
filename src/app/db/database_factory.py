"""
数据库连接工厂模块
支持 SQLite、MySQL、PostgreSQL 三种数据库
支持从配置文件或环境变量读取配置

环境变量优先级高于配置文件，使用 DATABASE__ 前缀对应 settings.database 节点：
- DATABASE__TYPE: 数据库类型 (sqlite/mysql/postgresql)
- DATABASE__HOST: 数据库主机
- DATABASE__PORT: 数据库端口
- DATABASE__USERNAME: 用户名
- DATABASE__PASSWORD: 密码
- DATABASE__DATABASE: 数据库名
- DATABASE__SQLITE_PATH: SQLite 数据库文件路径
"""

import os
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

import log
from app.core.settings import settings

# 环境变量名称映射
ENV_VAR_MAP = {
    "type": "DATABASE__TYPE",
    "host": "DATABASE__HOST",
    "port": "DATABASE__PORT",
    "username": "DATABASE__USERNAME",
    "password": "DATABASE__PASSWORD",
    "database": "DATABASE__DATABASE",
    "sqlite_path": "DATABASE__SQLITE_PATH",
}


class DatabaseFactory:
    """数据库连接工厂类"""

    # 支持的数据库类型
    SQLITE = "sqlite"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"

    @staticmethod
    def get_database_url(
        db_type: str | None = None,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
        db_path: str | None = None,
    ) -> str:
        """
        根据配置生成数据库连接URL

        :param db_type: 数据库类型 (sqlite/mysql/postgresql)
        :param host: 数据库主机
        :param port: 数据库端口
        :param username: 用户名
        :param password: 密码
        :param database: 数据库名
        :param db_path: SQLite数据库文件路径
        :return: SQLAlchemy连接URL
        """
        if db_type is None:
            db_type = DatabaseFactory._get_config_db_type()

        db_type = db_type.lower()

        if db_type == DatabaseFactory.SQLITE:
            # SQLite 连接URL
            if db_path is None:
                raise ValueError("SQLite数据库需要提供db_path参数")
            return f"sqlite:///{db_path}?check_same_thread=False"

        elif db_type == DatabaseFactory.MYSQL:
            # MySQL 连接URL
            host = host or DatabaseFactory._get_config_value("host", "localhost")
            port = port or DatabaseFactory._get_config_value("port", 3306)
            username = username or DatabaseFactory._get_config_value("username", "")
            password = password or DatabaseFactory._get_config_value("password", "")
            database = database or DatabaseFactory._get_config_value("database", "nexus_media")

            # 对密码进行URL编码
            encoded_password = quote_plus(str(password)) if password else ""
            return f"mysql+pymysql://{username}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4"

        elif db_type == DatabaseFactory.POSTGRESQL:
            # PostgreSQL 连接URL
            host = host or DatabaseFactory._get_config_value("host", "localhost")
            port = port or DatabaseFactory._get_config_value("port", 5432)
            username = username or DatabaseFactory._get_config_value("username", "postgres")
            password = password or DatabaseFactory._get_config_value("password", "")
            database = database or DatabaseFactory._get_config_value("database", "nexus_media")

            # 对密码进行URL编码
            encoded_password = quote_plus(str(password)) if password else ""
            return f"postgresql+psycopg2://{username}:{encoded_password}@{host}:{port}/{database}"

        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")

    @staticmethod
    def _ensure_database_exists(db_type: str, database: str):
        """
        确保数据库存在，如果不存在则自动创建

        :param db_type: 数据库类型
        :param database: 数据库名
        """
        if db_type == DatabaseFactory.SQLITE:
            # SQLite 数据库文件会在首次连接时自动创建
            return

        try:
            if db_type == DatabaseFactory.MYSQL:
                # 获取连接参数（不指定数据库）
                host = DatabaseFactory._get_config_value("host", "localhost")
                port = DatabaseFactory._get_config_value("port", 3306)
                username = DatabaseFactory._get_config_value("username", "")
                password = DatabaseFactory._get_config_value("password", "")

                # 连接到 MySQL 服务器（不指定数据库）
                server_url = f"mysql+pymysql://{quote_plus(str(username))}:{quote_plus(str(password))}@{host}:{port}"
                engine = sa_create_engine(server_url)

                with engine.connect() as conn:
                    # 创建数据库（如果不存在）
                    conn.execute(
                        text(
                            f"CREATE DATABASE IF NOT EXISTS {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )

                engine.dispose()

            elif db_type == DatabaseFactory.POSTGRESQL:
                # 获取连接参数（不指定数据库）
                host = DatabaseFactory._get_config_value("host", "localhost")
                port = DatabaseFactory._get_config_value("port", 5432)
                username = DatabaseFactory._get_config_value("username", "postgres")
                password = DatabaseFactory._get_config_value("password", "")

                # 连接到 PostgreSQL 服务器（使用 postgres 数据库）
                server_url = f"postgresql+psycopg2://{quote_plus(str(username))}:{quote_plus(str(password))}@{host}:{port}/postgres"
                engine = sa_create_engine(server_url, isolation_level="AUTOCOMMIT")

                with engine.connect() as conn:
                    # 检查数据库是否存在
                    result = conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :database"),
                        {"database": database},
                    )
                    if not result.fetchone():
                        # 创建数据库
                        conn.execute(text(f"CREATE DATABASE {database}"))

                engine.dispose()

        except (OSError, ValueError) as e:
            # 记录错误但不抛出，让后续连接尝试决定最终成败
            log.warn(f"[DatabaseFactory]自动创建数据库 {database} 失败: {e}")

    @staticmethod
    def create_engine(db_type: str | None = None, db_path: str | None = None, **kwargs) -> Engine:
        """
        创建数据库引擎

        :param db_type: 数据库类型，默认从配置文件获取
        :param db_path: SQLite数据库文件路径，默认从配置路径获取
        :param kwargs: 额外的引擎参数
        :return: SQLAlchemy Engine对象
        """
        if db_type is None:
            db_type = DatabaseFactory._get_config_db_type()

        db_type = db_type.lower()

        # 构建连接URL
        if db_type == DatabaseFactory.SQLITE:
            if db_path is None:
                # 优先使用配置的 sqlite_path（DATABASE__SQLITE_PATH），否则落在 data/user.db
                configured = DatabaseFactory._get_config_value("sqlite_path")
                db_path = configured or os.path.join(settings.data_path, "user.db")
            url = DatabaseFactory.get_database_url(db_type, db_path=db_path)
        else:
            # MySQL/PostgreSQL 使用配置中的数据库名
            database = DatabaseFactory._get_config_value("database", "nexus_media")

            # 自动创建数据库（如果不存在）
            DatabaseFactory._ensure_database_exists(db_type, database)

            url = DatabaseFactory.get_database_url(db_type, database=database)

        # 构建引擎参数
        engine_kwargs = {
            "echo": kwargs.get("echo", False),
        }

        if db_type == DatabaseFactory.SQLITE:
            # SQLite 文件库使用 NullPool，每个请求后关闭连接，配合 busy_timeout 让 SQLite 自身排队
            # :memory: 库使用 StaticPool 保证所有操作在同一连接内
            is_memory = db_path == ":memory:"
            if is_memory:
                engine_kwargs["poolclass"] = kwargs.get("poolclass", StaticPool)
                engine_kwargs["connect_args"] = {"check_same_thread": False}
            else:
                engine_kwargs["poolclass"] = kwargs.get("poolclass", NullPool)
                engine_kwargs["connect_args"] = {"timeout": 30}
        else:
            # MySQL/PostgreSQL 连接池配置
            engine_kwargs["poolclass"] = QueuePool
            engine_kwargs["pool_size"] = kwargs.get("pool_size", 10)
            engine_kwargs["max_overflow"] = kwargs.get("max_overflow", 10)
            engine_kwargs["pool_timeout"] = kwargs.get("pool_timeout", 60)
            engine_kwargs["pool_recycle"] = kwargs.get("pool_recycle", 1800)
            engine_kwargs["pool_pre_ping"] = True

        engine = create_engine(url, **engine_kwargs)

        # 执行数据库特定的初始化
        DatabaseFactory._init_database(engine, db_type)

        return engine

    @staticmethod
    def _setup_sqlite_pragmas(engine: Engine) -> None:
        """为 SQLite 引擎注册 connect 事件监听器，确保每个连接都执行性能/并发 PRAGMA."""

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA journal_mode=WAL;")
            dbapi_conn.execute("PRAGMA synchronous=NORMAL;")
            dbapi_conn.execute("PRAGMA cache_size=-64000;")
            dbapi_conn.execute("PRAGMA temp_store=MEMORY;")
            dbapi_conn.execute("PRAGMA mmap_size=268435456;")
            dbapi_conn.execute("PRAGMA busy_timeout=30000;")
            dbapi_conn.execute("PRAGMA wal_autocheckpoint=1000;")

    @staticmethod
    def _init_database(engine: Engine, db_type: str):
        """
        执行数据库特定的初始化设置

        :param engine: SQLAlchemy Engine
        :param db_type: 数据库类型
        """
        if db_type == DatabaseFactory.SQLITE:
            DatabaseFactory._setup_sqlite_pragmas(engine)
            # 立即对当前连接执行一次 PRAGMA，保证 create_engine 后立即可用
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

    @staticmethod
    def is_sqlite(engine: Engine) -> bool:
        """检查是否是SQLite数据库"""
        return "sqlite" in engine.url.drivername.lower()

    @staticmethod
    def is_mysql(engine: Engine) -> bool:
        """检查是否是MySQL数据库"""
        return "mysql" in engine.url.drivername.lower()

    @staticmethod
    def is_postgresql(engine: Engine) -> bool:
        """检查是否是PostgreSQL数据库"""
        return "postgresql" in engine.url.drivername.lower()

    @staticmethod
    def _get_env_value(key: str, default: Any = None) -> Any:
        """
        从环境变量获取配置值

        :param key: 配置键名
        :param default: 默认值
        :return: 环境变量值或默认值
        """
        env_var = ENV_VAR_MAP.get(key)
        if env_var:
            value = os.environ.get(env_var)
            if value is not None:
                # 处理端口等数值类型
                if key == "port" and value:
                    try:
                        return int(value)
                    except ValueError:
                        return default
                return value
        return default

    @staticmethod
    def _get_config_db_type() -> str:
        """从环境变量或配置中获取数据库类型"""
        # 优先从环境变量读取
        env_type = DatabaseFactory._get_env_value("type")
        if env_type:
            return env_type.lower()

        # 从配置文件读取
        try:
            config = settings.get()
            db_config = config.get("database", {})
            db_type = db_config.get("type", "sqlite")
            return db_type.lower()
        except (AttributeError, KeyError, TypeError):
            return DatabaseFactory.SQLITE

    @staticmethod
    def _get_config_value(key: str, default: Any = None) -> Any:
        """从环境变量或配置中获取数据库配置值（环境变量优先级更高）"""
        # 优先从环境变量读取
        env_value = DatabaseFactory._get_env_value(key, default)
        if env_value is not None and env_value != default:
            return env_value

        # 从配置文件读取
        try:
            config = settings.get()
            db_config = config.get("database", {})
            return db_config.get(key, default)
        except (AttributeError, KeyError, TypeError):
            return default

    @staticmethod
    def get_main_db_url() -> str:
        """获取主数据库连接URL"""
        db_type = DatabaseFactory._get_config_db_type()

        if db_type == DatabaseFactory.SQLITE:
            db_path = os.path.join(settings.data_path, "user.db")
            return DatabaseFactory.get_database_url(db_type, db_path=db_path)
        else:
            database = DatabaseFactory._get_config_value("database", "nexus_media")
            return DatabaseFactory.get_database_url(db_type, database=database)

    @staticmethod
    def get_alembic_url() -> str:
        """获取Alembic迁移使用的连接URL（用于主数据库）"""
        return DatabaseFactory.get_main_db_url()


class DatabaseDialect:
    """数据库方言处理类，处理不同数据库的语法差异"""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.is_sqlite = DatabaseFactory.is_sqlite(engine)
        self.is_mysql = DatabaseFactory.is_mysql(engine)
        self.is_postgresql = DatabaseFactory.is_postgresql(engine)

    def get_text_type(self) -> str:
        """获取文本类型"""
        if self.is_postgresql:
            return "TEXT"
        elif self.is_mysql:
            return "LONGTEXT"
        return "TEXT"

    def get_current_timestamp(self) -> str:
        """获取当前时间戳函数"""
        if self.is_postgresql:
            return "CURRENT_TIMESTAMP"
        elif self.is_mysql:
            return "NOW()"
        return "datetime('now')"

    def get_date_format(self, column: str, format_str: str) -> str:
        """
        获取日期格式化函数

        :param column: 列名
        :param format_str: 格式字符串
        :return: 数据库特定的日期格式化表达式
        """
        if self.is_postgresql:
            # PostgreSQL 使用 TO_CHAR
            pg_format = format_str.replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
            return f"TO_CHAR({column}, '{pg_format}')"
        elif self.is_mysql:
            # MySQL 使用 DATE_FORMAT
            return f"DATE_FORMAT({column}, '{format_str}')"
        else:
            # SQLite 使用 strftime
            return f"strftime('{format_str}', {column})"

    def get_limit_clause(self, limit: int, offset: int = 0) -> str:
        """
        获取LIMIT子句

        :param limit: 限制数量
        :param offset: 偏移量
        :return: LIMIT子句
        """
        if offset > 0:
            return f"LIMIT {limit} OFFSET {offset}"
        return f"LIMIT {limit}"

    def get_random_function(self) -> str:
        """获取随机函数"""
        if self.is_postgresql:
            return "RANDOM()"
        elif self.is_mysql:
            return "RAND()"
        return "RANDOM()"

    def get_concat_function(self, *args) -> str:
        """
        获取字符串连接函数

        :param args: 要连接的字符串或列名
        :return: 连接表达式
        """
        if self.is_postgresql:
            return " || ".join(args)
        elif self.is_mysql:
            return f"CONCAT({', '.join(args)})"
        else:
            return " || ".join(args)
