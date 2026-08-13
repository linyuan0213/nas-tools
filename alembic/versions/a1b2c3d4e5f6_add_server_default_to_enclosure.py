"""add server_default to SEARCH_RESULT_INFO.ENCLOSURE

Revision ID: a1b2c3d4e5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-06-23

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "1ee439ce9b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    if has_table("SEARCH_RESULT_INFO") and has_column("SEARCH_RESULT_INFO", "ENCLOSURE"):
        op.alter_column(
            "SEARCH_RESULT_INFO",
            "ENCLOSURE",
            existing_type=sa.String(8192),
            server_default="",
            existing_nullable=False,
        )


def downgrade() -> None:
    if has_table("SEARCH_RESULT_INFO") and has_column("SEARCH_RESULT_INFO", "ENCLOSURE"):
        op.alter_column(
            "SEARCH_RESULT_INFO",
            "ENCLOSURE",
            existing_type=sa.String(8192),
            server_default=None,
            existing_nullable=False,
        )
