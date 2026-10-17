"""calendar events carry the deal their title names

Revision ID: 0056
Revises: 0055
"""
import sqlalchemy as sa

from alembic import op

revision = '0056'
down_revision = '0055'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('calendar_event', sa.Column('deal', sa.String(length=128), nullable=True))
    op.create_index('ix_calendar_event_deal', 'calendar_event', ['deal'])


def downgrade() -> None:
    op.drop_index('ix_calendar_event_deal', table_name='calendar_event')
    op.drop_column('calendar_event', 'deal')
