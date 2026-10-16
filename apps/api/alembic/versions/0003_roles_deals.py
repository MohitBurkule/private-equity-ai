"""api key role and deal scope, document deal

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('api_key', sa.Column('role', sa.String(length=16), server_default='analyst', nullable=False))
    op.add_column('api_key', sa.Column('deals', sa.Text(), nullable=True))
    op.add_column('document', sa.Column('deal', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_document_deal'), 'document', ['deal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_deal'), table_name='document')
    op.drop_column('document', 'deal')
    op.drop_column('api_key', 'deals')
    op.drop_column('api_key', 'role')
