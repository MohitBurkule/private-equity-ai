"""Cached /ask answers, keyed on question, visible documents and their hashes, and prompt version

Revision ID: 20261017_2000_answer_cache
Revises: 20261017_1955_llm_usage
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_2000_answer_cache'
down_revision = '20261017_1955_llm_usage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'answer_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.UniqueConstraint('tenant_id', 'key'),
    )
    op.create_index('ix_answer_cache_tenant_id', 'answer_cache', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_answer_cache_tenant_id', table_name='answer_cache')
    op.drop_table('answer_cache')
