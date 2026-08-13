"""add_seeds_columns_to_transfer_history

Revision ID: cf6482561ead
Revises: 7fff87651c62
Create Date: 2026-07-28

"""

import sqlalchemy as sa

from alembic import op

revision = "cf6482561ead"
down_revision = "7fff87651c62"
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
    if has_table("TRANSFER_HISTORY"):
        with op.batch_alter_table("TRANSFER_HISTORY") as batch_op:
            if not has_column("TRANSFER_HISTORY", "SEEDS_SEASON"):
                batch_op.add_column(sa.Column("SEEDS_SEASON", sa.Integer(), nullable=True))
            if not has_column("TRANSFER_HISTORY", "SEEDS_EPISODE"):
                batch_op.add_column(sa.Column("SEEDS_EPISODE", sa.Integer(), nullable=True))
            if not has_column("TRANSFER_HISTORY", "SEEDS_END_EPISODE"):
                batch_op.add_column(sa.Column("SEEDS_END_EPISODE", sa.Integer(), nullable=True))


def downgrade() -> None:
    if has_table("TRANSFER_HISTORY"):
        with op.batch_alter_table("TRANSFER_HISTORY") as batch_op:
            if has_column("TRANSFER_HISTORY", "SEEDS_END_EPISODE"):
                batch_op.drop_column("SEEDS_END_EPISODE")
            if has_column("TRANSFER_HISTORY", "SEEDS_EPISODE"):
                batch_op.drop_column("SEEDS_EPISODE")
            if has_column("TRANSFER_HISTORY", "SEEDS_SEASON"):
                batch_op.drop_column("SEEDS_SEASON")
