"""Valuation and round history: one cited row per round or mark from a user's export

Revision ID: 20261017_1900_valuation_round
Revises: 20261017_1830_deal_sponsor
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1900_valuation_round'
down_revision = '20261017_1830_deal_sponsor'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'valuation_round',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('company', sa.String(length=256), nullable=False),
        sa.Column('round_date', sa.String(length=10), nullable=False),
        sa.Column('round_type', sa.String(length=64), nullable=False),
        sa.Column('post_money', sa.Numeric(24, 6), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.Column('line', sa.Integer(), nullable=False),
    )
    op.create_index(op.f('ix_valuation_round_tenant_id'), 'valuation_round', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_valuation_round_tenant_id'), table_name='valuation_round')
    op.drop_table('valuation_round')
