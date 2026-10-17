"""Permission sync: API keys carry the person's external identity; synced documents carry the source's access list

Revision ID: 0049
Revises: 0048
"""
import sqlalchemy as sa

from alembic import op

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('api_key', sa.Column('identity', sa.String(256), nullable=True))
    op.add_column('document_source', sa.Column('acl', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('document_source', 'acl')
    op.drop_column('api_key', 'identity')
