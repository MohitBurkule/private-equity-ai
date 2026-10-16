"""fact review columns

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa

from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fact', sa.Column('reviewed_by', sa.String(length=64), nullable=True))
    op.add_column('fact', sa.Column('reviewed_at', sa.String(length=40), nullable=True))
    op.add_column('fact', sa.Column('review_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('fact', 'review_note')
    op.drop_column('fact', 'reviewed_at')
    op.drop_column('fact', 'reviewed_by')
