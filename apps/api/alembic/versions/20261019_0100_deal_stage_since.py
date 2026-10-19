"""Deal: when the deal entered its current stage, for stage-ageing alerts

Revision ID: 20261019_0100_deal_stage_since
Revises: 20261018_0700_deal_postmortem
"""
import sqlalchemy as sa

from alembic import op

revision = '20261019_0100_deal_stage_since'
down_revision = '20261018_0700_deal_postmortem'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal', sa.Column('stage_since', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('deal', 'stage_since')
