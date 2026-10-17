"""Ethical walls: per-deal list of people and groups that may not see the deal

Revision ID: 20261017_2020_deal_wall
Revises: 20261017_2010_firm_stamp
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_2020_deal_wall'
down_revision = '20261017_2010_firm_stamp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal', sa.Column('wall', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('deal', 'wall')
