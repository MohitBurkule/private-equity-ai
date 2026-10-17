"""deal MNPI flag: hidden from unscoped keys

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa

from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal', sa.Column('mnpi', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('deal', 'mnpi')
