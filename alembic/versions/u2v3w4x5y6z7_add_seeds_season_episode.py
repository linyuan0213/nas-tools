"""add SEEDS_SEASON/EPISODE to SEARCH_RESULT_INFO

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-07-28T23:24:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    for col in ("SEEDS_SEASON", "SEEDS_EPISODE", "SEEDS_END_EPISODE"):
        if not has_column("SEARCH_RESULT_INFO", col):
            if dialect_name == "sqlite":
                with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
                    batch_op.add_column(sa.Column(col, sa.Integer(), nullable=True))
            else:
                op.add_column("SEARCH_RESULT_INFO", sa.Column(col, sa.Integer(), nullable=True))


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    for col in ("SEEDS_END_EPISODE", "SEEDS_EPISODE", "SEEDS_SEASON"):
        if has_column("SEARCH_RESULT_INFO", col):
            if dialect_name == "sqlite":
                with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
                    batch_op.drop_column(col)
            else:
                op.drop_column("SEARCH_RESULT_INFO", col)
