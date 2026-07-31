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


def upgrade() -> None:
    with op.batch_alter_table("TRANSFER_HISTORY") as batch_op:
        batch_op.add_column(sa.Column("SEEDS_SEASON", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("SEEDS_EPISODE", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("SEEDS_END_EPISODE", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("TRANSFER_HISTORY") as batch_op:
        batch_op.drop_column("SEEDS_END_EPISODE")
        batch_op.drop_column("SEEDS_EPISODE")
        batch_op.drop_column("SEEDS_SEASON")
