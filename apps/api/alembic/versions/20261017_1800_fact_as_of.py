"""Fact as-of date, so a market figure says the day it was true

Revision ID: 20261017_1800_fact_as_of
Revises: 20261017_1745_docx_spans
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1800_fact_as_of'
down_revision = '20261017_1745_docx_spans'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fact', sa.Column('as_of', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('fact', 'as_of')
