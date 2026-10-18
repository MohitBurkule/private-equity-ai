"""Portfolio companies can map their own workbook labels to KPIs

Revision ID: 20261018_0300_company_label_map
Revises: 20261018_0200_memo_assign
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0300_company_label_map'
down_revision = '20261018_0200_memo_assign'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_company', sa.Column('label_map', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_company', 'label_map')
