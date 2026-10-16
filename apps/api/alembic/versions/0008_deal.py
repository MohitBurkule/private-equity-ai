"""deal workspace

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa

from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'deal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('stage', sa.String(length=16), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name'),
    )
    op.create_index(op.f('ix_deal_tenant_id'), 'deal', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_deal_tenant_id'), table_name='deal')
    op.drop_table('deal')
