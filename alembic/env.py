from logging.config import fileConfig

import sqlalchemy as sa
from alembic.script import ScriptDirectory

import log
from alembic import context
from app.db.database_factory import DatabaseFactory
from app.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_database_url():
    """
    获取数据库连接URL
    优先使用配置文件中的URL，如果没有则使用工厂生成
    """
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return DatabaseFactory.get_alembic_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_database_url()

    # 根据数据库类型配置不同的迁移选项
    dialect_opts = {"paramstyle": "named"}

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts=dialect_opts,
        render_as_batch=True,  # 支持SQLite的批量操作
        compare_type=False,  # 不比较列类型，避免历史遗留类型差异产生垃圾迁移
        compare_server_default=False,  # 不比较默认值
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # 使用工厂创建引擎
    connectable = DatabaseFactory.create_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # 支持SQLite的批量操作
            compare_type=False,  # 不比较列类型，避免历史遗留类型差异产生垃圾迁移
            compare_server_default=False,  # 不比较默认值
        )

        # 全新库判定：无 alembic_version 且无任何业务表 → 用模型直接建最新 schema 并 stamp 到 head。
        inspector = sa.inspect(connection)
        table_names = set(inspector.get_table_names())
        business_tables = {t for t in table_names if not t.startswith("alembic_") and not t.startswith("sqlite_")}
        has_version_table = "alembic_version" in table_names

        def _bootstrap_and_stamp() -> None:
            target_metadata.create_all(connection, checkfirst=True)
            script = ScriptDirectory.from_config(config)
            head_rev = script.get_current_head()
            connection.execute(
                sa.text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) NOT NULL, PRIMARY KEY (version_num))"
                )
            )
            # 冲突保护：并发/遗留状态下已有版本行时不再插入
            existing = connection.execute(sa.text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            if not existing:
                connection.execute(
                    sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": head_rev}
                )
            connection.commit()

        if not has_version_table and not business_tables:
            _bootstrap_and_stamp()
            return

        # "有业务表但无版本表"（如先跑过 create_all 的开发库）：
        # - SQLite（默认/开发库）：schema 恒由 create_all 按当前模型构建，直接补建缺失表并 stamp，
        #   避免重放 MySQL 导向的迁移链（SQLite 不支持其约束/类型 ALTER）；
        # - MySQL/PostgreSQL（生产）：走守卫迁移链，确保数据迁移（列变更/数据转换）执行，
        #   避免被永久跳过。
        if not has_version_table and business_tables and connection.dialect.name == "sqlite":
            log.warn(
                "[alembic]SQLite 数据库存在业务表但无 alembic_version（由 create_all 构建），"
                "已补建缺失表并 stamp 到 head；数据迁移请走 MySQL/PostgreSQL 流程"
            )
            _bootstrap_and_stamp()
            return

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
