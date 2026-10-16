"""alert emailed_at

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa

from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('alert', sa.Column('emailed_at', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('alert', 'emailed_at')
