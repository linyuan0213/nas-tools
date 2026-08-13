"""expand_rss_remove_rule_to_text

Revision ID: e5efa40afddb
Revises: d4efa40afddb
Create Date: 2026-07-05 08:00:00

Change RSS_RULE and REMOVE_RULE from VARCHAR(255) to TEXT to support large JSON rules.
"""

import sqlalchemy as sa

from alembic import op

revision = "e5efa40afddb"
down_revision = "d4efa40afddb"
branch_labels = None
depends_on = None


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table(table_name):
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade():
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "RSS_RULE"):
        op.alter_column(
            "SITE_BRUSH_TASK", "RSS_RULE", existing_type=sa.String(255), type_=sa.Text, existing_nullable=True
        )
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "REMOVE_RULE"):
        op.alter_column(
            "SITE_BRUSH_TASK", "REMOVE_RULE", existing_type=sa.String(255), type_=sa.Text, existing_nullable=True
        )


def downgrade():
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "RSS_RULE"):
        op.alter_column(
            "SITE_BRUSH_TASK", "RSS_RULE", existing_type=sa.Text, type_=sa.String(255), existing_nullable=True
        )
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "REMOVE_RULE"):
        op.alter_column(
            "SITE_BRUSH_TASK", "REMOVE_RULE", existing_type=sa.Text, type_=sa.String(255), existing_nullable=True
        )
