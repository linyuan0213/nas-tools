"""download_dir_text

Revision ID: d5e6f7a8b9c0
Revises: b3c4d5e6f7a8
Create Date: 2026-06-23 20:58:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str = "b3c4d5e6f7a8"
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
    if has_table("DOWNLOADER") and has_column("DOWNLOADER", "DOWNLOAD_DIR"):
        with op.batch_alter_table("DOWNLOADER", schema=None) as batch_op:
            batch_op.alter_column(
                "DOWNLOAD_DIR",
                existing_type=sa.String(length=255),
                type_=sa.Text,
                existing_nullable=False,
            )


def downgrade() -> None:
    if has_table("DOWNLOADER") and has_column("DOWNLOADER", "DOWNLOAD_DIR"):
        with op.batch_alter_table("DOWNLOADER", schema=None) as batch_op:
            batch_op.alter_column(
                "DOWNLOAD_DIR",
                existing_type=sa.Text,
                type_=sa.String(length=255),
                existing_nullable=False,
            )
