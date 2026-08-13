"""add_brush_rule_table

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-17 09:10:00.000000

"""

import sqlalchemy as sa
from sqlalchemy import Column, Integer, Sequence, String, Text

from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    if not has_table("SITE_BRUSH_RULE"):
        op.create_table(
            "SITE_BRUSH_RULE",
            Column("ID", Integer, Sequence("ID"), primary_key=True),
            Column("NAME", String(255), index=True),
            Column("RSS_RULE", Text, nullable=False, default=""),
            Column("REMOVE_RULE", Text, nullable=False, default=""),
            Column("STOP_RULE", Text, nullable=False, default=""),
            Column("LST_MOD_DATE", String(255)),
        )
    if not has_column("SITE_BRUSH_TASK", "RULE_ID"):
        try:
            op.add_column(
                "SITE_BRUSH_TASK",
                Column("RULE_ID", Integer, sa.ForeignKey("SITE_BRUSH_RULE.ID"), nullable=True),
            )
        except Exception:  # noqa: BLE001
            # SQLite 不支持 ADD COLUMN 携带外键；该列后续由拆分迁移接管，忽略即可
            pass


def downgrade():
    if has_column("SITE_BRUSH_TASK", "RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "RULE_ID")
    if has_table("SITE_BRUSH_RULE"):
        op.drop_table("SITE_BRUSH_RULE")
