"""Saved memo versions can be signed off by a named person, with a timestamp

Revision ID: 20261018_0400_memo_signoff
Revises: 20261018_0300_company_label_map
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0400_memo_signoff'
down_revision = '20261018_0300_company_label_map'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memo_signoff',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('memo_version.id'), nullable=False),
        sa.Column('approver', sa.String(length=64), nullable=False),
        sa.Column('signed_at', sa.String(length=40), nullable=False),
        sa.UniqueConstraint('version_id', 'approver'),
    )
    op.create_index('ix_memo_signoff_tenant_id', 'memo_signoff', ['tenant_id'])
    op.create_index('ix_memo_signoff_version_id', 'memo_signoff', ['version_id'])


def downgrade() -> None:
    op.drop_index('ix_memo_signoff_version_id', table_name='memo_signoff')
    op.drop_index('ix_memo_signoff_tenant_id', table_name='memo_signoff')
    op.drop_table('memo_signoff')
