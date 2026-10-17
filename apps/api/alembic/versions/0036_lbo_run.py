"""saved LBO runs with their request and result

Revision ID: 0036
Revises: 0035
"""
import sqlalchemy as sa

from alembic import op

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'lbo_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.Column('request', sa.Text(), nullable=False),
        sa.Column('result', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_lbo_run_tenant_id'), 'lbo_run', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lbo_run_tenant_id'), table_name='lbo_run')
    op.drop_table('lbo_run')
