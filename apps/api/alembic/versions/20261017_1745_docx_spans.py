"""DOCX paragraph spans on pages, so a cited quote maps to paragraph numbers

Revision ID: 20261017_1745_docx_spans
Revises: 20261017_1725_kpi_kind
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1745_docx_spans'
down_revision = '20261017_1725_kpi_kind'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('page', sa.Column('spans', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('page', 'spans')
