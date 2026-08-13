"""rename rss tables to subscribe tables

Revision ID: f8a9b0c1d2e3
Revises: ef7dde90afd7
Create Date: 2026-06-01 06:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f8a9b0c1d2e3"
down_revision = "ef7dde90afd7"
branch_labels = None
depends_on = None


def has_table(table_name):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


TABLE_RENAMES = [
    ("RSS_HISTORY", "SUBSCRIBE_HISTORY"),
    ("RSS_MOVIES", "SUBSCRIBE_MOVIES"),
    ("RSS_TORRENTS", "SUBSCRIBE_TORRENTS"),
    ("RSS_TV_EPISODES", "SUBSCRIBE_TV_EPISODES"),
    ("RSS_TVS", "SUBSCRIBE_TVS"),
]


def upgrade():
    for old_name, new_name in TABLE_RENAMES:
        if has_table(old_name):
            op.rename_table(old_name, new_name)


def downgrade():
    for old_name, new_name in TABLE_RENAMES:
        if has_table(new_name):
            op.rename_table(new_name, old_name)
