"""secondary-market holdings import

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa

from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'holding',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('platform', sa.String(length=64), nullable=False),
        sa.Column('company', sa.String(length=256), nullable=False),
        sa.Column('shares', sa.Numeric(24, 6), nullable=False),
        sa.Column('price', sa.Numeric(24, 6), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('acquired', sa.String(length=10), nullable=True),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('line', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_holding_tenant_id'), 'holding', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_holding_tenant_id'), table_name='holding')
    op.drop_table('holding')
