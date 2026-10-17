"""per-deal role overrides on API keys

Revision ID: 0030
Revises: 0029
"""
import sqlalchemy as sa

from alembic import op

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('api_key', sa.Column('deal_roles', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('api_key', 'deal_roles')
