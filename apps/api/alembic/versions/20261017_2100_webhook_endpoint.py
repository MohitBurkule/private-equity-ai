"""Outbound webhook endpoints for tenant systems

Revision ID: 20261017_2100_webhook_endpoint
Revises: 20261017_2010_firm_stamp
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_2100_webhook_endpoint'
down_revision = '20261017_2010_firm_stamp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'webhook_endpoint',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('secret', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_endpoint_tenant_id'), 'webhook_endpoint', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_endpoint_tenant_id'), table_name='webhook_endpoint')
    op.drop_table('webhook_endpoint')
