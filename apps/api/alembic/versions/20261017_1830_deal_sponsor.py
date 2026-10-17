"""Deal sponsor, so seen-before can match a sponsor we have dealt with

Revision ID: 20261017_1830_deal_sponsor
Revises: 20261017_1800_fact_as_of
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1830_deal_sponsor'
down_revision = '20261017_1800_fact_as_of'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal', sa.Column('sponsor', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('deal', 'sponsor')
