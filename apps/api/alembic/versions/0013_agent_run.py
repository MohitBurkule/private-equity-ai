"""agent and workflow run log

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa

from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('steps', sa.Text(), nullable=False),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_run_tenant_id'), 'agent_run', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_run_tenant_id'), table_name='agent_run')
    op.drop_table('agent_run')
