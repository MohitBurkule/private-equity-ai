"""Log each language-model call: model, characters in and out, latency

Revision ID: 20261018_0600_llm_call_log
Revises: 20261018_0500_inbox_alias
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0600_llm_call_log'
down_revision = '20261018_0500_inbox_alias'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_call',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('at', sa.String(length=40), nullable=False),
        sa.Column('model', sa.String(length=160), nullable=False),
        sa.Column('chars_in', sa.Integer(), nullable=False),
        sa.Column('chars_out', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
    )
    op.create_index('ix_llm_call_tenant_id', 'llm_call', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_llm_call_tenant_id', table_name='llm_call')
    op.drop_table('llm_call')
