"""firm memo templates

Revision ID: 0051
Revises: 0050
"""
import sqlalchemy as sa

from alembic import op

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memo_template',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('sections', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_memo_template_tenant_name'),
    )
    op.create_index(op.f('ix_memo_template_tenant_id'), 'memo_template', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memo_template_tenant_id'), table_name='memo_template')
    op.drop_table('memo_template')
