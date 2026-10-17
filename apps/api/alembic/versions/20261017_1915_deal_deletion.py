"""Pending deal deletion requests: the first of two steps before a deal is removed

Revision ID: 20261017_1915_deal_deletion
Revises: 20261017_1900_valuation_round
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1915_deal_deletion'
down_revision = '20261017_1900_valuation_round'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'deal_deletion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=200), nullable=False),
        sa.Column('requested_by', sa.String(length=64), nullable=False),
        sa.Column('requested_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_deal_deletion_tenant_id', 'deal_deletion', ['tenant_id'])
    op.create_index('ix_deal_deletion_deal', 'deal_deletion', ['deal'])


def downgrade() -> None:
    op.drop_index('ix_deal_deletion_deal', table_name='deal_deletion')
    op.drop_index('ix_deal_deletion_tenant_id', table_name='deal_deletion')
    op.drop_table('deal_deletion')
