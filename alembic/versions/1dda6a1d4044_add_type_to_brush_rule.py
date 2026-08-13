"""add type to brush rule

Revision ID: 1dda6a1d4044
Revises: f65506008fd7
Create Date: 2026-07-01 14:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1dda6a1d4044"
down_revision: str | None = "ee2445e35880"
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
    if has_table("SITE_BRUSH_RULE") and not has_column("SITE_BRUSH_RULE", "TYPE"):
        op.add_column(
            "SITE_BRUSH_RULE",
            sa.Column("TYPE", sa.String(10), nullable=False, server_default="all"),
        )


def downgrade() -> None:
    if has_table("SITE_BRUSH_RULE") and has_column("SITE_BRUSH_RULE", "TYPE"):
        op.drop_column("SITE_BRUSH_RULE", "TYPE")
