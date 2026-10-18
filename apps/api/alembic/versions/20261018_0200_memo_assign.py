"""Memo comments can be assigned to someone and marked resolved

Revision ID: 20261018_0200_memo_assign
Revises: 20261018_0100_page_figure
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0200_memo_assign'
down_revision = '20261018_0100_page_figure'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('memo_comment', sa.Column('assignee', sa.String(length=64), nullable=True))
    op.add_column('memo_comment', sa.Column('status', sa.String(length=16), server_default='open', nullable=False))


def downgrade() -> None:
    op.drop_column('memo_comment', 'status')
    op.drop_column('memo_comment', 'assignee')
