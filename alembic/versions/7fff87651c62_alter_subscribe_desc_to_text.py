"""alter_subscribe_desc_to_text

Revision ID: 7fff87651c62
Revises: s1r2c3h4r5e6
Create Date: 2026-07-28 08:17:39.613372

"""

import sqlalchemy as sa

from alembic import op

revision = "7fff87651c62"
down_revision = "s1r2c3h4r5e6"
branch_labels = None
depends_on = None

TABLES = ("SUBSCRIBE_HISTORY", "SUBSCRIBE_MOVIES", "SUBSCRIBE_TVS")


def upgrade() -> None:
    for tbl in TABLES:
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.alter_column("DESC", existing_type=sa.String(255), type_=sa.Text, nullable=True)


def downgrade() -> None:
    for tbl in TABLES:
        with op.batch_alter_table(tbl) as batch_op:
            batch_op.alter_column("DESC", existing_type=sa.Text, type_=sa.String(255), nullable=True)
