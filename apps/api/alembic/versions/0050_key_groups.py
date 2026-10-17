"""API keys carry the external groups of their person, for group grants on synced documents

Revision ID: 0050
Revises: 0049
"""
import sqlalchemy as sa

from alembic import op

revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('api_key', sa.Column('groups', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('api_key', 'groups')
