"""user_level_default_empty_string

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-23 21:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    if not inspect(conn).has_table(table):
        return False
    cols = {c["name"].upper() for c in inspect(conn).get_columns(table)}
    return column.upper() in cols


def upgrade() -> None:
    for table, col in [("SITE_STATISTICS_HISTORY", "USER_LEVEL"), ("SITE_USER_INFO_STATS", "USER_LEVEL")]:
        if _column_exists(table, col):
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(
                    col,
                    existing_type=sa.String(length=255),
                    server_default=text("''"),
                    existing_nullable=True,
                )


def downgrade() -> None:
    for table, col in [("SITE_STATISTICS_HISTORY", "USER_LEVEL"), ("SITE_USER_INFO_STATS", "USER_LEVEL")]:
        if _column_exists(table, col):
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(
                    col,
                    existing_type=sa.String(length=255),
                    server_default=None,
                    existing_nullable=True,
                )
