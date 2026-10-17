"""deal-level checklist items

Revision ID: 0024
Revises: 0023
"""
import sqlalchemy as sa

from alembic import op

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'deal_checklist_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_deal_checklist_item_tenant_id', 'deal_checklist_item', ['tenant_id'])
    op.create_index('ix_deal_checklist_item_deal', 'deal_checklist_item', ['deal'])


def downgrade() -> None:
    op.drop_index('ix_deal_checklist_item_deal', table_name='deal_checklist_item')
    op.drop_index('ix_deal_checklist_item_tenant_id', table_name='deal_checklist_item')
    op.drop_table('deal_checklist_item')
