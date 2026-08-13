"""add_search_session_id_to_search_result_info

Revision ID: cdf1444102e6
Revises: 7e029912f153
Create Date: 2026-05-31 11:43:45.360587

"""

import sqlalchemy as sa
from sqlalchemy import Column

from alembic import op

revision = "cdf1444102e6"
down_revision = "7e029912f153"
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
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if has_table("SEARCH_RESULT_INFO") and not has_column("SEARCH_RESULT_INFO", "SEARCH_SESSION_ID"):
        op.add_column("SEARCH_RESULT_INFO", Column("SEARCH_SESSION_ID", sa.String(64), nullable=True))
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_SEARCH_RESULT_INFO_SEARCH_SESSION_ID "
                "ON SEARCH_RESULT_INFO (SEARCH_SESSION_ID)"
            )
        )
    # 将唯一约束从 (PAGEURL, SITE) 改为 (PAGEURL, SITE, SEARCH_SESSION_ID)
    # 以支持多 session 隔离；SQLite 不支持 ALTER CONSTRAINT，用索引替代
    if has_table("SEARCH_RESULT_INFO"):
        conn = op.get_bind()
        conn.execute(sa.text("DROP INDEX IF EXISTS uq_search_pageurl_site"))
        conn.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_search_pageurl_site_session "
                "ON SEARCH_RESULT_INFO (PAGEURL, SITE, SEARCH_SESSION_ID)"
            )
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS uq_search_pageurl_site_session"))
    if has_table("SEARCH_RESULT_INFO"):
        conn.execute(
            sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_search_pageurl_site ON SEARCH_RESULT_INFO (PAGEURL, SITE)")
        )
    if has_column("SEARCH_RESULT_INFO", "SEARCH_SESSION_ID"):
        op.drop_index("ix_SEARCH_RESULT_INFO_SEARCH_SESSION_ID", table_name="SEARCH_RESULT_INFO")
        op.drop_column("SEARCH_RESULT_INFO", "SEARCH_SESSION_ID")
