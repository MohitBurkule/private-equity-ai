"""Per-tenant daily LLM usage, so a daily cap can be enforced

Revision ID: 20261017_1955_llm_usage
Revises: 20261017_1945_tenant_pii
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1955_llm_usage'
down_revision = '20261017_1945_tenant_pii'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False),
        sa.Column('chars', sa.Integer(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'day'),
    )
    op.create_index('ix_llm_usage_tenant_id', 'llm_usage', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_llm_usage_tenant_id', table_name='llm_usage')
    op.drop_table('llm_usage')
