"""deal note edit time

Revision ID: 0057
Revises: 0056
"""
import sqlalchemy as sa

from alembic import op

revision = '0057'
down_revision = '0056'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal_note', sa.Column('edited_at', sa.String(length=40), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('deal_note', 'edited_at')
