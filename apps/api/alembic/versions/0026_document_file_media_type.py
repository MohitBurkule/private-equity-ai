"""media type of the kept original, so a filing's HTML is not served as a PDF

Revision ID: 0026
Revises: 0025
"""
import sqlalchemy as sa

from alembic import op

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('document_file', sa.Column('media_type', sa.String(length=64), nullable=False,
                                             server_default='application/pdf'))


def downgrade() -> None:
    op.drop_column('document_file', 'media_type')
