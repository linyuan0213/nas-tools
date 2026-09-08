"""add ADD_DATE to SUBSCRIBE_MOVIES and SUBSCRIBE_TVS

Revision ID: f5c99c5c67c5
Revises: cd49db2e67f9
Create Date: 2026-09-08

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'f5c99c5c67c5'
down_revision = 'cd49db2e67f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('SUBSCRIBE_MOVIES', sa.Column('ADD_DATE', sa.String(255), nullable=True))
    op.add_column('SUBSCRIBE_TVS', sa.Column('ADD_DATE', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('SUBSCRIBE_TVS', 'ADD_DATE')
    op.drop_column('SUBSCRIBE_MOVIES', 'ADD_DATE')
