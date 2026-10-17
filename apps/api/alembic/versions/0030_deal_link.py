"""deal-to-CRM record links for two-way stage sync

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
    op.create_table(
        'deal_link',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('connector', sa.String(length=32), nullable=False),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('last_local', sa.String(length=16), nullable=False),
        sa.Column('last_external', sa.String(length=16), nullable=False),
        sa.UniqueConstraint('tenant_id', 'connector', 'external_id'),
    )
    op.create_index('ix_deal_link_tenant_id', 'deal_link', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_deal_link_tenant_id', table_name='deal_link')
    op.drop_table('deal_link')
