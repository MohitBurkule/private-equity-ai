"""Tenant PII flag: strip personal identifiers from outbound digests, chat posts and exports

Revision ID: 20261017_1945_tenant_pii
Revises: 20261017_1915_deal_deletion
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1945_tenant_pii'
down_revision = '20261017_1915_deal_deletion'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tenant', sa.Column('pii_redaction', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('tenant', 'pii_redaction')
