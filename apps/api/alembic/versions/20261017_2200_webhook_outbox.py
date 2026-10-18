"""Durable outbox for webhook posts, written in the same transaction as the move

Revision ID: 20261017_2200_webhook_outbox
Revises: 20261017_2110_heads_merge
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_2200_webhook_outbox'
down_revision = '20261017_2110_heads_merge'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'webhook_outbox',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('endpoint_id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=64), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.String(length=32), nullable=False),
        sa.Column('last_error', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_webhook_outbox_tenant_id'), 'webhook_outbox', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_outbox_tenant_id'), table_name='webhook_outbox')
    op.drop_table('webhook_outbox')
