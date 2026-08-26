"""drop unused is_superadmin column from RBAC_USERS

Revision ID: 7d81beaface3
Revises: a2b3c4d5e6f7
Create Date: 2026-08-26
"""

import sqlalchemy as sa

from alembic import op

revision = "7d81beaface3"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # is_superadmin 列从未参与权限判定（超管由 superadmin 角色决定），历史遗留恒为 0
    if _has_column("RBAC_USERS", "IS_SUPERADMIN"):
        op.drop_column("RBAC_USERS", "IS_SUPERADMIN")


def downgrade() -> None:
    if not _has_column("RBAC_USERS", "IS_SUPERADMIN"):
        op.add_column(
            "RBAC_USERS",
            sa.Column("IS_SUPERADMIN", sa.Integer(), nullable=False, server_default="0"),
        )
