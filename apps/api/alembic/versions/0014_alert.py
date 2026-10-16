"""proactive alert inbox

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa

from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=256), nullable=False),
        sa.Column('fact_ids', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='new', nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'dedupe_key'),
    )
    op.create_index(op.f('ix_alert_tenant_id'), 'alert', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alert_tenant_id'), table_name='alert')
    op.drop_table('alert')
