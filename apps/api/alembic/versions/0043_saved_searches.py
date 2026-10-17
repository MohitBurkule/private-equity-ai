"""saved searches: a named query the team reruns under its own access

Revision ID: 0043
Revises: 0042
"""
import sqlalchemy as sa

from alembic import op

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_search',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(length=40), nullable=False, server_default=''),
        sa.UniqueConstraint('tenant_id', 'name'),
    )
    op.create_index('ix_saved_search_tenant_id', 'saved_search', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_saved_search_tenant_id', table_name='saved_search')
    op.drop_table('saved_search')
