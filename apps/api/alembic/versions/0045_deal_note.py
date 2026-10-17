"""shared notes on a deal

Revision ID: 0045
Revises: 0044
"""
import sqlalchemy as sa

from alembic import op

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'deal_note',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('author', sa.String(length=64), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
    )
    op.create_index(op.f('ix_deal_note_tenant_id'), 'deal_note', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_deal_note_deal'), 'deal_note', ['deal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_deal_note_deal'), table_name='deal_note')
    op.drop_index(op.f('ix_deal_note_tenant_id'), table_name='deal_note')
    op.drop_table('deal_note')
