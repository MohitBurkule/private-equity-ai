"""outreach review queue: drafts reviewed by a senior person before one is sent

Revision ID: 0038
Revises: 0036
"""
import sqlalchemy as sa

from alembic import op

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'outreach_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('target_id', sa.Integer(), sa.ForeignKey('target.id'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('sender', sa.String(length=120), nullable=False),
        sa.Column('firm', sa.String(length=120), nullable=False),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('subject', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('reviewed_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('sent_at', sa.String(length=40), nullable=True),
    )
    op.create_index('ix_outreach_item_tenant_id', 'outreach_item', ['tenant_id'])
    op.create_index('ix_outreach_item_target_id', 'outreach_item', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_outreach_item_target_id', table_name='outreach_item')
    op.drop_index('ix_outreach_item_tenant_id', table_name='outreach_item')
    op.drop_table('outreach_item')
