"""站点 id 统一小写 Alembic 迁移测试（SQLAlchemy Core，跨方言通用）。"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION = "itj05t3fierl_unify_site_id_lowercase"
_MIGRATION_FILE = f"{_MIGRATION}.py"

# 仅声明迁移涉及的列，用 MetaData.create_all 生成方言适配的 DDL
_META = sa.MetaData()
_INDEXER_SITE_CONFIG = sa.Table(
    "INDEXER_SITE_CONFIG",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("SITE_NAME", sa.String(255)),
)
_SITE_BRUSH_RULE = sa.Table(
    "SITE_BRUSH_RULE",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("SITE", sa.String(255)),
)
_SITE_BRUSH_TASK = sa.Table(
    "SITE_BRUSH_TASK",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("SITE", sa.String(255)),
)
_BRUSH_EVENT_LOG = sa.Table(
    "BRUSH_EVENT_LOG",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("SITE_NAME", sa.String(255)),
)
_CONFIG_SITE = sa.Table(
    "CONFIG_SITE",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("NAME", sa.String(255)),
)
_CONFIG_USER_RSS = sa.Table(
    "CONFIG_USER_RSS",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("SITES", sa.Text),
)
_SUBSCRIBE_MOVIES = sa.Table(
    "SUBSCRIBE_MOVIES",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("RSS_SITES", sa.Text),
    sa.Column("SEARCH_SITES", sa.Text),
)
_SUBSCRIBE_TVS = sa.Table(
    "SUBSCRIBE_TVS",
    _META,
    sa.Column("ID", sa.Integer, primary_key=True),
    sa.Column("RSS_SITES", sa.Text),
    sa.Column("SEARCH_SITES", sa.Text),
)

_EXACT_TABLES = [
    ("INDEXER_SITE_CONFIG", "SITE_NAME", ["U2", "PANDA", "mteam"]),
    ("SITE_BRUSH_RULE", "SITE", ["U2", "TCCF"]),
    ("SITE_BRUSH_TASK", "SITE", ["PANDA", "HDKylin"]),
    ("BRUSH_EVENT_LOG", "SITE_NAME", ["ToSky", "mteam"]),
    ("CONFIG_SITE", "NAME", ["U2", "HDTime"]),
]


@pytest.fixture
def mig_engine():
    engine = sa.create_engine("sqlite://")
    _META.create_all(engine)
    yield engine
    engine.dispose()


def _seed(conn) -> None:
    for i, (table_name, column, values) in enumerate(_EXACT_TABLES):
        table = _META.tables[table_name]
        for j, v in enumerate(values):
            conn.execute(table.insert().values(ID=i * 10 + j, **{column: v}))
    conn.execute(_META.tables["CONFIG_USER_RSS"].insert().values(ID=1, SITES='["U2", "OKPT", "mteam"]'))
    for table_name in ("SUBSCRIBE_MOVIES", "SUBSCRIBE_TVS"):
        conn.execute(
            _META.tables[table_name].insert().values(ID=1, RSS_SITES='["PANDA"]', SEARCH_SITES='["U2", "PTSKIT"]')
        )


def _migration_module():
    """按文件路径加载迁移模块（alembic/versions 无 __init__.py，非包）"""
    versions_dir = Path(__file__).resolve().parents[3] / "alembic" / "versions"
    spec = importlib.util.spec_from_file_location(f"alembic_versions_{_MIGRATION}", versions_dir / _MIGRATION_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"迁移模块加载失败: {_MIGRATION_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(conn, fn) -> None:
    """绑定真实 Operations 到迁移模块的 op，执行 upgrade/downgrade"""
    module = _migration_module()
    ctx = MigrationContext.configure(conn)
    setattr(module, "op", Operations(ctx))
    fn(module)


def _upgrade(conn) -> None:
    _run_migration(conn, lambda mod: mod.upgrade())


def _downgrade(conn) -> None:
    _run_migration(conn, lambda mod: mod.downgrade())


class TestSiteIdUnifyMigration:
    def test_upgrade_remaps_exact_columns(self, mig_engine):
        with mig_engine.connect() as conn:
            _seed(conn)
            _upgrade(conn)
            names = {r[0] for r in conn.execute(sa.select(_META.tables["INDEXER_SITE_CONFIG"].c.SITE_NAME)).all()}
        assert "u2" in names and "U2" not in names
        assert "panda" in names and "PANDA" not in names
        assert "mteam" in names

    def test_upgrade_remaps_all_exact_tables(self, mig_engine):
        with mig_engine.connect() as conn:
            _seed(conn)
            _upgrade(conn)
            brush_rule = {r[0] for r in conn.execute(sa.select(_META.tables["SITE_BRUSH_RULE"].c.SITE)).all()}
            brush_task = {r[0] for r in conn.execute(sa.select(_META.tables["SITE_BRUSH_TASK"].c.SITE)).all()}
            event_log = {r[0] for r in conn.execute(sa.select(_META.tables["BRUSH_EVENT_LOG"].c.SITE_NAME)).all()}
            config_site = {r[0] for r in conn.execute(sa.select(_META.tables["CONFIG_SITE"].c.NAME)).all()}
        assert brush_rule == {"u2", "tccf"}
        assert brush_task == {"panda", "hdkylin"}
        assert event_log == {"tosky", "mteam"}
        assert config_site == {"u2", "hdtime"}

    def test_upgrade_remaps_json_arrays(self, mig_engine):
        with mig_engine.connect() as conn:
            _seed(conn)
            _upgrade(conn)
            rss = conn.execute(sa.select(_META.tables["CONFIG_USER_RSS"].c.SITES)).scalar()
            movies = conn.execute(
                sa.select(
                    _META.tables["SUBSCRIBE_MOVIES"].c.RSS_SITES,
                    _META.tables["SUBSCRIBE_MOVIES"].c.SEARCH_SITES,
                )
            ).fetchone()
            tvs = conn.execute(
                sa.select(_META.tables["SUBSCRIBE_TVS"].c.RSS_SITES, _META.tables["SUBSCRIBE_TVS"].c.SEARCH_SITES)
            ).fetchone()
        assert rss == '["u2", "okpt", "mteam"]'
        assert movies[0] == '["panda"]'
        assert movies[1] == '["u2", "ptskit"]'
        assert tvs[0] == '["panda"]'
        assert tvs[1] == '["u2", "ptskit"]'

    def test_downgrade_restores_old_ids(self, mig_engine):
        with mig_engine.connect() as conn:
            _seed(conn)
            _upgrade(conn)
            _downgrade(conn)
            names = {r[0] for r in conn.execute(sa.select(_META.tables["INDEXER_SITE_CONFIG"].c.SITE_NAME)).all()}
            rss = conn.execute(sa.select(_META.tables["CONFIG_USER_RSS"].c.SITES)).scalar()
        assert "U2" in names and "u2" not in names
        assert "PANDA" in names and "panda" not in names
        assert rss == '["U2", "OKPT", "mteam"]'
