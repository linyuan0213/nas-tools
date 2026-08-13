"""alter_download_history_desc_to_text

Revision ID: 246a1b8afcdc
Revises: cf6482561ead
Create Date: 2026-07-28
"""

import sqlalchemy as sa

from alembic import op

revision = "246a1b8afcdc"
down_revision = "cf6482561ead"
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


def upgrade() -> None:
    if has_table("DOWNLOAD_HISTORY") and has_column("DOWNLOAD_HISTORY", "DESC"):
        with op.batch_alter_table("DOWNLOAD_HISTORY") as batch_op:
            batch_op.alter_column("DESC", existing_type=sa.String(255), type_=sa.Text, nullable=True)


def downgrade() -> None:
    if has_table("DOWNLOAD_HISTORY") and has_column("DOWNLOAD_HISTORY", "DESC"):
        with op.batch_alter_table("DOWNLOAD_HISTORY") as batch_op:
            batch_op.alter_column("DESC", existing_type=sa.Text, type_=sa.String(255), nullable=True)
