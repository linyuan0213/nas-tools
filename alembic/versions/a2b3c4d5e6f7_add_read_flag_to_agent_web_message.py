"""add read flag to agent web message

Revision ID: a2b3c4d5e6f7
Revises: 01d6f010bb7d
Create Date: 2026-08-14
"""

import sqlalchemy as sa

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "01d6f010bb7d"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("AGENT_WEB_MESSAGE", "READ"):
        op.add_column("AGENT_WEB_MESSAGE", sa.Column("READ", sa.Boolean(), nullable=False, server_default="0"))
    if not _has_column("AGENT_WEB_MESSAGE", "READ_AT"):
        op.add_column("AGENT_WEB_MESSAGE", sa.Column("READ_AT", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _has_column("AGENT_WEB_MESSAGE", "READ_AT"):
        op.drop_column("AGENT_WEB_MESSAGE", "READ_AT")
    if _has_column("AGENT_WEB_MESSAGE", "READ"):
        op.drop_column("AGENT_WEB_MESSAGE", "READ")
