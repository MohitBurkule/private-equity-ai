"""saved connector connections

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa

from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'connection',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('connector', sa.String(length=32), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=True),
        sa.Column('options', sa.Text(), nullable=False),
        sa.Column('token_sealed', sa.Text(), nullable=False),
        sa.Column('interval_minutes', sa.Integer(), nullable=True),
        sa.Column('last_run', sa.String(length=40), nullable=True),
        sa.Column('last_status', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_connection_tenant_id'), 'connection', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_connection_tenant_id'), table_name='connection')
    op.drop_table('connection')
