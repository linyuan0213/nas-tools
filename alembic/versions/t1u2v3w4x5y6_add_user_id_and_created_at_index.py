"""add USER_ID and CREATED_AT index to SEARCH_RESULT_INFO

Revision ID: t1u2v3w4x5y6
Revises: 246a1b8afcdc
Create Date: 2026-07-28T07:15:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "t1u2v3w4x5y6"
down_revision = "246a1b8afcdc"
branch_labels = None
depends_on = None


def has_column(table_name, column_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def has_index(table_name, index_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    for idx in inspector.get_indexes(table_name):
        if idx.get("name") == index_name:
            return True
    return False


def upgrade() -> None:
    if not has_column("SEARCH_RESULT_INFO", "USER_ID"):
        dialect_name = op.get_bind().dialect.name
        if dialect_name == "sqlite":
            with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
                batch_op.add_column(sa.Column("USER_ID", sa.String(64), nullable=True))
        else:
            op.add_column("SEARCH_RESULT_INFO", sa.Column("USER_ID", sa.String(64), nullable=True))

    if not has_column("SEARCH_RESULT_INFO", "CREATED_AT"):
        dialect_name = op.get_bind().dialect.name
        if dialect_name == "sqlite":
            with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
                batch_op.add_column(
                    sa.Column("CREATED_AT", sa.DateTime(), nullable=False, server_default=sa.func.now())
                )
        else:
            op.add_column(
                "SEARCH_RESULT_INFO",
                sa.Column("CREATED_AT", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            )

    if not has_index("SEARCH_RESULT_INFO", "ix_search_result_created_at"):
        op.create_index("ix_search_result_created_at", "SEARCH_RESULT_INFO", ["CREATED_AT"])

    if not has_index("SEARCH_RESULT_INFO", "ix_search_result_user_id"):
        op.create_index("ix_search_result_user_id", "SEARCH_RESULT_INFO", ["USER_ID"])


def downgrade() -> None:
    if has_index("SEARCH_RESULT_INFO", "ix_search_result_user_id"):
        op.drop_index("ix_search_result_user_id", table_name="SEARCH_RESULT_INFO")
    if has_index("SEARCH_RESULT_INFO", "ix_search_result_created_at"):
        op.drop_index("ix_search_result_created_at", table_name="SEARCH_RESULT_INFO")
    if has_column("SEARCH_RESULT_INFO", "USER_ID"):
        dialect_name = op.get_bind().dialect.name
        if dialect_name == "sqlite":
            with op.batch_alter_table("SEARCH_RESULT_INFO") as batch_op:
                batch_op.drop_column("USER_ID")
        else:
            op.drop_column("SEARCH_RESULT_INFO", "USER_ID")
