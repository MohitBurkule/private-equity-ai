"""Deals carry aliases and registry identifiers (CIK, LEI) so a filing matches the deal exactly

Revision ID: 0051
Revises: 0050
"""
import sqlalchemy as sa

from alembic import op

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deal', sa.Column('aliases', sa.Text(), nullable=True))
    op.add_column('deal', sa.Column('cik', sa.String(length=10), nullable=True))
    op.add_column('deal', sa.Column('lei', sa.String(length=20), nullable=True))
    op.create_index('ix_deal_cik', 'deal', ['cik'])
    op.create_index('ix_deal_lei', 'deal', ['lei'])


def downgrade():
    op.drop_index('ix_deal_lei', table_name='deal')
    op.drop_index('ix_deal_cik', table_name='deal')
    op.drop_column('deal', 'lei')
    op.drop_column('deal', 'cik')
    op.drop_column('deal', 'aliases')
