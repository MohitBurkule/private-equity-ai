"""workflow schedule"""
import sqlalchemy as sa

from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workflow_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('params', sa.Text(), nullable=False),
        sa.Column('every_days', sa.Integer(), nullable=False),
        sa.Column('recipients', sa.Text(), nullable=False),
        sa.Column('next_run', sa.String(length=40), nullable=False),
        sa.Column('last_run', sa.String(length=40), nullable=True),
        sa.Column('last_status', sa.String(length=16), nullable=True),
        sa.Column('last_result', sa.Text(), nullable=True),
        sa.Column('active', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflow_schedule_tenant_id'), 'workflow_schedule', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workflow_schedule_tenant_id'), table_name='workflow_schedule')
    op.drop_table('workflow_schedule')
