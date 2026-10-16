"""evaluation run history

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa

from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'eval_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('suite', sa.String(length=64), nullable=False),
        sa.Column('metrics', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('ran_at', sa.String(length=40), nullable=False),
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_eval_run_tenant_id'), 'eval_run', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_eval_run_suite'), 'eval_run', ['suite'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_eval_run_suite'), table_name='eval_run')
    op.drop_index(op.f('ix_eval_run_tenant_id'), table_name='eval_run')
    op.drop_table('eval_run')
