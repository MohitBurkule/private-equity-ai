"""saved peer sets per deal

Revision ID: 0054
Revises: 0053
"""
import sqlalchemy as sa

from alembic import op

revision = '0054'
down_revision = '0053'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'peer_set',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('items', sa.Text(), nullable=False),
        sa.Column('dropped', sa.Text(), nullable=False),
        sa.Column('refreshed_at', sa.String(length=40), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_peer_set_tenant_id', 'peer_set', ['tenant_id'])
    op.create_index('ix_peer_set_deal', 'peer_set', ['deal'])


def downgrade() -> None:
    op.drop_index('ix_peer_set_deal', table_name='peer_set')
    op.drop_index('ix_peer_set_tenant_id', table_name='peer_set')
    op.drop_table('peer_set')
