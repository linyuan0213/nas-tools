"""rename message_client switchs to switches

Revision ID: f65506008fd7
Revises: f82cb58980d0
Create Date: 2026-06-13 05:56:13.101011

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision = "f65506008fd7"
down_revision = "f82cb58980d0"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    if not inspect(conn).has_table(table):
        return False
    cols = {c["name"].upper() for c in inspect(conn).get_columns(table)}
    return column.upper() in cols


def upgrade() -> None:
    if _column_exists("MESSAGE_CLIENT", "SWITCHS") and not _column_exists("MESSAGE_CLIENT", "SWITCHES"):
        with op.batch_alter_table("MESSAGE_CLIENT", schema=None) as batch_op:
            batch_op.alter_column(
                "SWITCHS",
                new_column_name="SWITCHES",
                existing_type=sa.Text,
            )


def downgrade() -> None:
    if _column_exists("MESSAGE_CLIENT", "SWITCHES") and not _column_exists("MESSAGE_CLIENT", "SWITCHS"):
        with op.batch_alter_table("MESSAGE_CLIENT", schema=None) as batch_op:
            batch_op.alter_column(
                "SWITCHES",
                new_column_name="SWITCHS",
                existing_type=sa.Text,
            )
