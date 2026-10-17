"""calendar meetings for the board-cadence watcher

Revision ID: 0027
Revises: 0026
"""
import sqlalchemy as sa

from alembic import op

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'calendar_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('external_id', sa.String(length=512), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('starts_at', sa.String(length=10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False, server_default=''),
        sa.Column('company', sa.String(length=256), nullable=True),
        sa.Column('board', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint('tenant_id', 'source', 'external_id'),
    )
    op.create_index('ix_calendar_event_tenant_id', 'calendar_event', ['tenant_id'])
    op.create_index('ix_calendar_event_company', 'calendar_event', ['company'])


def downgrade() -> None:
    op.drop_index('ix_calendar_event_company', table_name='calendar_event')
    op.drop_index('ix_calendar_event_tenant_id', table_name='calendar_event')
    op.drop_table('calendar_event')
