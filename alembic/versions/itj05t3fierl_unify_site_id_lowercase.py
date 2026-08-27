"""统一站点 id 为小写并重映射存量数据

站点配置仓库将 14 个大写/混合大小写站点 id 统一为小写（U2->u2、PANDA->panda 等）。
存量数据库中各表可能仍引用旧 id，此迁移将其重映射为新值。
全部通过 SQLAlchemy Core 表达式执行，兼容 SQLite / MySQL / PostgreSQL。

Revision ID: itj05t3fierl
Revises: 7d81beaface3
Create Date: 2026-08-27
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "itj05t3fierl"
down_revision = "7d81beaface3"
branch_labels = None
depends_on = None

# 旧站点 id -> 新（小写）站点 id
SITE_ID_MAP = {
    "AGSVPT": "agsvpt",
    "ECUSTPT": "ecustpt",
    "HDarea": "hdarea",
    "HDHome": "hdhome",
    "HDKylin": "hdkylin",
    "HDTime": "hdtime",
    "HDU": "hdu",
    "HDZone": "hdzone",
    "OKPT": "okpt",
    "PANDA": "panda",
    "PTSKIT": "ptskit",
    "TCCF": "tccf",
    "ToSky": "tosky",
    "U2": "u2",
}

# 站点 id 精确匹配列（值为站点 id）
_EXACT_COLUMNS = [
    ("INDEXER_SITE_CONFIG", "SITE_NAME"),
    ("SITE_BRUSH_RULE", "SITE"),
    ("SITE_BRUSH_TASK", "SITE"),
    ("BRUSH_EVENT_LOG", "SITE_NAME"),
    ("CONFIG_SITE", "NAME"),
]

# 站点 id JSON 数组列（值为 ["mteam", "U2"] 形式），按主键 ID 回写
_JSON_ARRAY_COLUMNS = [
    ("CONFIG_USER_RSS", "SITES"),
    ("SUBSCRIBE_MOVIES", "RSS_SITES"),
    ("SUBSCRIBE_MOVIES", "SEARCH_SITES"),
    ("SUBSCRIBE_TVS", "RSS_SITES"),
    ("SUBSCRIBE_TVS", "SEARCH_SITES"),
]


def _table_has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def _table(table: str, *columns: str) -> sa.TableClause:
    """按名称构造轻量 TableClause（免去检查同名模型，跨方言通用）"""
    return sa.table(table, *[sa.column(col) for col in columns])


def _remap_json_array(text: str | None, id_map: dict | None = None) -> str | None:
    """重映射 JSON 数组中的旧站点 id，未变化时原样返回。"""
    id_map = id_map or SITE_ID_MAP
    if not text:
        return text
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(data, list):
        return text
    new = [id_map.get(str(item), item) for item in data]
    if new == data:
        return text
    return json.dumps(new, ensure_ascii=False)


def upgrade() -> None:
    bind = op.get_bind()

    for table, column in _EXACT_COLUMNS:
        if not _table_has_column(table, column):
            continue
        tbl = _table(table, column)
        for old_id, new_id in SITE_ID_MAP.items():
            op.execute(sa.update(tbl).where(tbl.c[column] == old_id).values({column: new_id}))

    for table, column in _JSON_ARRAY_COLUMNS:
        if not _table_has_column(table, column):
            continue
        tbl = _table(table, "ID", column)
        rows = bind.execute(sa.select(tbl.c.ID, tbl.c[column])).fetchall()
        for row_id, raw in rows:
            updated = _remap_json_array(raw)
            if updated is not None and updated != raw:
                op.execute(sa.update(tbl).where(tbl.c.ID == row_id).values({column: updated}))


def downgrade() -> None:
    bind = op.get_bind()
    reverse_map = {new_id: old_id for old_id, new_id in SITE_ID_MAP.items()}

    for table, column in _EXACT_COLUMNS:
        if not _table_has_column(table, column):
            continue
        tbl = _table(table, column)
        for new_id, old_id in reverse_map.items():
            op.execute(sa.update(tbl).where(tbl.c[column] == new_id).values({column: old_id}))

    for table, column in _JSON_ARRAY_COLUMNS:
        if not _table_has_column(table, column):
            continue
        tbl = _table(table, "ID", column)
        rows = bind.execute(sa.select(tbl.c.ID, tbl.c[column])).fetchall()
        for row_id, raw in rows:
            updated = _remap_json_array(raw, reverse_map)
            if updated is not None and updated != raw:
                op.execute(sa.update(tbl).where(tbl.c.ID == row_id).values({column: updated}))
