"""homepage enrichment fields on targets

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa

from alembic import op

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('target', sa.Column('website', sa.Text(), nullable=True))
    op.add_column('target', sa.Column('web_title', sa.Text(), nullable=True))
    op.add_column('target', sa.Column('web_description', sa.Text(), nullable=True))
    op.add_column('target', sa.Column('web_site_name', sa.Text(), nullable=True))
    op.add_column('target', sa.Column('web_checked_at', sa.String(length=40), nullable=True))


def downgrade() -> None:
    for col in ('web_checked_at', 'web_site_name', 'web_description', 'web_title', 'website'):
        op.drop_column('target', col)
