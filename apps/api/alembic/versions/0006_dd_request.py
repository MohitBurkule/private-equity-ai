"""due diligence request list

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa

from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dd_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dd_request_tenant_id'), 'dd_request', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dd_request_deal'), 'dd_request', ['deal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_dd_request_deal'), table_name='dd_request')
    op.drop_index(op.f('ix_dd_request_tenant_id'), table_name='dd_request')
    op.drop_table('dd_request')
