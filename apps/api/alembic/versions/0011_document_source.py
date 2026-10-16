"""connector provenance per document

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa

from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_source',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('connector', sa.String(length=32), nullable=False),
        sa.Column('external_id', sa.String(length=512), nullable=False),
        sa.Column('version', sa.String(length=128), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_source_tenant_id'), 'document_source', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_document_source_document_id'), 'document_source', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_source_document_id'), table_name='document_source')
    op.drop_index(op.f('ix_document_source_tenant_id'), table_name='document_source')
    op.drop_table('document_source')
