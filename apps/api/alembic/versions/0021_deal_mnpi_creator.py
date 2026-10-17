"""record which key created an MNPI deal, so the creator keeps access

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa

from alembic import op

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deal', sa.Column('created_by', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('deal', 'created_by')
