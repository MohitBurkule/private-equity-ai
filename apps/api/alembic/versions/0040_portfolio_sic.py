"""portfolio companies carry a SIC code, so add-on search can match on it beyond the sector

Revision ID: 0040
Revises: 0039
"""
import sqlalchemy as sa

from alembic import op

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_company', sa.Column('sic', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_company', 'sic')
