"""meeting bodies and the deal notes they become

Revision ID: 0058
Revises: 0057
"""
import sqlalchemy as sa

from alembic import op

revision = '0058'
down_revision = '0057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('calendar_event', sa.Column('body', sa.Text(), nullable=False, server_default=''))
    op.add_column('deal_note', sa.Column('calendar_event_id', sa.Integer(), nullable=True))
    op.add_column('deal_note', sa.Column('source_url', sa.Text(), nullable=True))
    op.create_index('ix_deal_note_calendar_event_id', 'deal_note', ['calendar_event_id'])


def downgrade() -> None:
    op.drop_index('ix_deal_note_calendar_event_id', table_name='deal_note')
    op.drop_column('deal_note', 'source_url')
    op.drop_column('deal_note', 'calendar_event_id')
    op.drop_column('calendar_event', 'body')
