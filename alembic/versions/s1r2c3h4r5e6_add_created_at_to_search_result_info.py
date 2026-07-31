"""add created_at to search result info

Revision ID: s1r2c3h4r5e6
Revises: w1x2y3z4a5b6
Create Date: 2026-07-24T10:42:38.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "s1r2c3h4r5e6"
down_revision = "5x21ti0zeo0y"
branch_labels = None
depends_on = None


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    if has_column("SEARCH_RESULT_INFO", "CREATED_AT"):
        return
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
            batch_op.add_column(sa.Column("CREATED_AT", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    else:
        op.add_column(
            "SEARCH_RESULT_INFO",
            sa.Column("CREATED_AT", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    if not has_column("SEARCH_RESULT_INFO", "CREATED_AT"):
        return
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
            batch_op.drop_column("CREATED_AT")
    else:
        op.drop_column("SEARCH_RESULT_INFO", "CREATED_AT")
