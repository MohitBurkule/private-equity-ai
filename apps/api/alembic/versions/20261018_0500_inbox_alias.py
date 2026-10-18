"""Portfolio companies can have an inbox alias that their KPI packs are mailed to

Revision ID: 20261018_0500_inbox_alias
Revises: 20261018_0400_memo_signoff
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0500_inbox_alias'
down_revision = '20261018_0400_memo_signoff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_company', sa.Column('inbox_alias', sa.String(length=64), nullable=True))
    op.create_index('ix_portfolio_company_inbox_alias', 'portfolio_company', ['inbox_alias'])


def downgrade() -> None:
    op.drop_index('ix_portfolio_company_inbox_alias', table_name='portfolio_company')
    op.drop_column('portfolio_company', 'inbox_alias')
