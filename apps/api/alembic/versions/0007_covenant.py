"""covenant tests on portfolio KPIs

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa

from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'covenant',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('kpi_metric', sa.String(length=128), nullable=False),
        sa.Column('operator', sa.String(length=2), nullable=False),
        sa.Column('threshold_fact_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['portfolio_company.id']),
        sa.ForeignKeyConstraint(['threshold_fact_id'], ['fact.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_covenant_tenant_id'), 'covenant', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_covenant_tenant_id'), table_name='covenant')
    op.drop_table('covenant')
