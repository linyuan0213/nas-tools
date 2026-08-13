"""add_api_key_bearer_token_headers_to_config_site

Revision ID: f82cb58980d0
Revises: 1fd6712c2b1f
Create Date: 2026-06-03 09:28:33.865508

"""

import json

import sqlalchemy as sa
from sqlalchemy import Column, Text

from alembic import op

revision = "f82cb58980d0"
down_revision = "1fd6712c2b1f"
branch_labels = None
depends_on = None


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if not has_column("CONFIG_SITE", "API_KEY"):
        op.add_column("CONFIG_SITE", Column("API_KEY", Text, nullable=True))
    if not has_column("CONFIG_SITE", "BEARER_TOKEN"):
        op.add_column("CONFIG_SITE", Column("BEARER_TOKEN", Text, nullable=True))
    if not has_column("CONFIG_SITE", "HEADERS"):
        op.add_column("CONFIG_SITE", Column("HEADERS", Text, nullable=True))

    # 数据迁移：将 NOTE 中的 headers 提取到 HEADERS 字段
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT ID, NOTE FROM CONFIG_SITE")).fetchall()
    for row in rows:
        note = row[1]
        if not note:
            continue
        try:
            note_dict = json.loads(note) if isinstance(note, str) else note
            headers = note_dict.get("headers")
            if headers:
                conn.execute(
                    sa.text("UPDATE CONFIG_SITE SET HEADERS = :headers WHERE ID = :id"),
                    {"headers": headers if isinstance(headers, str) else json.dumps(headers), "id": row[0]},
                )
        except Exception:
            pass


def downgrade():
    if has_column("CONFIG_SITE", "HEADERS"):
        op.drop_column("CONFIG_SITE", "HEADERS")
    if has_column("CONFIG_SITE", "BEARER_TOKEN"):
        op.drop_column("CONFIG_SITE", "BEARER_TOKEN")
    if has_column("CONFIG_SITE", "API_KEY"):
        op.drop_column("CONFIG_SITE", "API_KEY")
