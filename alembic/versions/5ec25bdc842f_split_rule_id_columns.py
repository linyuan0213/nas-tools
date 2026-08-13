"""split rule id columns

Revision ID: 5ec25bdc842f
Revises: 1dda6a1d4044
Create Date: 2026-07-01 14:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5ec25bdc842f"
down_revision: str | None = "1dda6a1d4044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "RSS_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("RSS_RULE_ID", sa.Integer(), nullable=True))
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("REMOVE_RULE_ID", sa.Integer(), nullable=True))
    if has_table("SITE_BRUSH_TASK") and not has_column("SITE_BRUSH_TASK", "STOP_RULE_ID"):
        op.add_column("SITE_BRUSH_TASK", sa.Column("STOP_RULE_ID", sa.Integer(), nullable=True))
    if has_table("SITE_BRUSH_TASK"):
        op.create_foreign_key(
            "fk_site_brush_task_rss_rule_id",
            "SITE_BRUSH_TASK",
            "SITE_BRUSH_RULE",
            ["RSS_RULE_ID"],
            ["ID"],
        )
        op.create_foreign_key(
            "fk_site_brush_task_remove_rule_id",
            "SITE_BRUSH_TASK",
            "SITE_BRUSH_RULE",
            ["REMOVE_RULE_ID"],
            ["ID"],
        )
        op.create_foreign_key(
            "fk_site_brush_task_stop_rule_id",
            "SITE_BRUSH_TASK",
            "SITE_BRUSH_RULE",
            ["STOP_RULE_ID"],
            ["ID"],
        )


def downgrade() -> None:
    if has_table("SITE_BRUSH_TASK"):
        op.drop_constraint("fk_site_brush_task_stop_rule_id", "SITE_BRUSH_TASK", type_="foreignkey")
        op.drop_constraint("fk_site_brush_task_remove_rule_id", "SITE_BRUSH_TASK", type_="foreignkey")
        op.drop_constraint("fk_site_brush_task_rss_rule_id", "SITE_BRUSH_TASK", type_="foreignkey")
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "STOP_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "STOP_RULE_ID")
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "REMOVE_RULE_ID")
    if has_table("SITE_BRUSH_TASK") and has_column("SITE_BRUSH_TASK", "RSS_RULE_ID"):
        op.drop_column("SITE_BRUSH_TASK", "RSS_RULE_ID")
