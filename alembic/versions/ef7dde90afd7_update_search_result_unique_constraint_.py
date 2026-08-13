"""update_search_result_unique_constraint_for_session

Revision ID: ef7dde90afd7
Revises: cdf1444102e6
Create Date: 2026-05-31 12:58:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "ef7dde90afd7"
down_revision = "cdf1444102e6"
branch_labels = None
depends_on = None


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def upgrade():
    # 创建唯一索引 (PAGEURL, SITE, SEARCH_SESSION_ID)
    # SQLite 使用 IF NOT EXISTS 避免与模型 create_all 重复创建冲突
    if has_table("SEARCH_RESULT_INFO"):
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_search_pageurl_site_session "
                "ON SEARCH_RESULT_INFO (PAGEURL, SITE, SEARCH_SESSION_ID)"
            )
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS uq_search_pageurl_site_session"))
