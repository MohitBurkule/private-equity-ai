"""Deals carry the SIC code of their target, the same key portfolio companies use

Revision ID: 0048
Revises: 0047
"""
import sqlalchemy as sa

from alembic import op

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deal', sa.Column('sic', sa.String(length=8), nullable=True))


def downgrade():
    op.drop_column('deal', 'sic')
