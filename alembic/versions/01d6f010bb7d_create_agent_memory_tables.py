"""create agent memory tables

Revision ID: 01d6f010bb7d
Revises: u2v3w4x5y6z7
Create Date: 2026-08-11
"""

import sqlalchemy as sa

from alembic import op

revision = "01d6f010bb7d"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("AGENT_CONVERSATION"):
        op.create_table(
            "AGENT_CONVERSATION",
            sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("USER_ID", sa.String(64), nullable=False, server_default=""),
            sa.Column("CHANNEL", sa.String(32), nullable=False, server_default="web"),
            sa.Column("SESSION_ID", sa.String(128), nullable=False, server_default=""),
            sa.Column("SUMMARY", sa.Text(), nullable=False, server_default=""),
            sa.Column("TOKEN_USAGE", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=True),
            sa.Column("UPDATED_AT", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("USER_ID", "CHANNEL", "SESSION_ID", name="uq_agent_conv_user_channel_session"),
        )
    if not _has_table("AGENT_MESSAGE"):
        op.create_table(
            "AGENT_MESSAGE",
            sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "CONVERSATION_ID",
                sa.Integer(),
                sa.ForeignKey("AGENT_CONVERSATION.ID", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("ROLE", sa.String(16), nullable=False, server_default="user"),
            sa.Column("CONTENT", sa.Text(), nullable=False, server_default=""),
            sa.Column("TOOL_CALLS", sa.JSON(), nullable=True),
            sa.Column("TOKENS", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=True),
            sa.Index("idx_agent_msg_conversation", "CONVERSATION_ID", "ID"),
        )
    if not _has_table("AGENT_WEB_MESSAGE"):
        op.create_table(
            "AGENT_WEB_MESSAGE",
            sa.Column("ID", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("USER_ID", sa.String(64), nullable=False, server_default=""),
            sa.Column("KIND", sa.String(16), nullable=False, server_default="notify"),
            sa.Column("TITLE", sa.Text(), nullable=False, server_default=""),
            sa.Column("CONTENT", sa.Text(), nullable=False, server_default=""),
            sa.Column("IMAGE", sa.Text(), nullable=False, server_default=""),
            sa.Column("URL", sa.Text(), nullable=False, server_default=""),
            sa.Column("ITEMS", sa.JSON(), nullable=True),
            sa.Column("CREATED_AT", sa.DateTime(), nullable=True),
            sa.Index("idx_agent_web_msg_user", "USER_ID", "ID"),
        )


def downgrade() -> None:
    for table in ("AGENT_WEB_MESSAGE", "AGENT_MESSAGE", "AGENT_CONVERSATION"):
        if _has_table(table):
            op.drop_table(table)
