"""original PDF bytes kept per document, for highlighted page images

Revision ID: 0025
Revises: 0024
"""
import sqlalchemy as sa

from alembic import op

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_file',
        sa.Column('document_id', sa.String(length=64), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
    )
    op.create_index('ix_document_file_tenant_id', 'document_file', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_document_file_tenant_id', table_name='document_file')
    op.drop_table('document_file')
