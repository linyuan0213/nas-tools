"""add plugin market source

Revision ID: p7k9mkt4q2wx
Revises: itj05t3fierl
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "p7k9mkt4q2wx"
down_revision = "itj05t3fierl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "PLUGIN_MARKET_SOURCE",
        sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("SOURCE_ID", sa.String(length=128), nullable=False),
        sa.Column("NAME", sa.String(length=255), nullable=False),
        sa.Column("URL", sa.String(length=1024), nullable=False),
        sa.Column("PUBLIC_KEY", sa.Text(), nullable=True),
        sa.Column("ENABLED", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("AUTO_UPDATE", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("LAST_SYNC_AT", sa.String(length=64), nullable=True),
        sa.Column("LAST_ERROR", sa.Text(), nullable=True),
        sa.UniqueConstraint("SOURCE_ID", name="uq_plugin_market_source_source_id"),
    )
    op.create_index("ix_plugin_market_source_source_id", "PLUGIN_MARKET_SOURCE", ["SOURCE_ID"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plugin_market_source_source_id", table_name="PLUGIN_MARKET_SOURCE")
    op.drop_table("PLUGIN_MARKET_SOURCE")
