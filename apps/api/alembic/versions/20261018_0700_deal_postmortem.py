"""Human-written post-mortem per deal: outcome, lesson, and an optional source link

Revision ID: 20261018_0700_deal_postmortem
Revises: 20261018_0600_llm_call_log
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0700_deal_postmortem'
down_revision = '20261018_0600_llm_call_log'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'deal_postmortem',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('lesson', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        sa.Column('recorded_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_deal_postmortem_tenant_id', 'deal_postmortem', ['tenant_id'])
    op.create_index('ix_deal_postmortem_deal', 'deal_postmortem', ['deal'])


def downgrade() -> None:
    op.drop_index('ix_deal_postmortem_deal', table_name='deal_postmortem')
    op.drop_index('ix_deal_postmortem_tenant_id', table_name='deal_postmortem')
    op.drop_table('deal_postmortem')
