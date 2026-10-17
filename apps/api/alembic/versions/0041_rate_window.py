"""per-tenant request counts for the replica-shared rate limit (RATE_LIMIT_BACKEND=postgres)

Revision ID: 0041
Revises: 0040
"""
import sqlalchemy as sa

from alembic import op

revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rate_window',
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('minute', sa.Integer(), nullable=False),
        sa.Column('n', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('tenant_id', 'minute'),
    )


def downgrade() -> None:
    op.drop_table('rate_window')
