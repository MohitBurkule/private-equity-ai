"""append-only IC decision log per deal: outcome, rationale, dissent

Revision ID: 0046
Revises: 0045
"""
import sqlalchemy as sa

from alembic import op

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ic_decision',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('dissent', sa.Text(), nullable=True),
        sa.Column('dissenter', sa.String(length=128), nullable=True),
        sa.Column('recorded_at', sa.String(length=40), nullable=False),
    )
    op.create_index(op.f('ix_ic_decision_tenant_id'), 'ic_decision', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_ic_decision_deal'), 'ic_decision', ['deal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ic_decision_deal'), table_name='ic_decision')
    op.drop_index(op.f('ix_ic_decision_tenant_id'), table_name='ic_decision')
    op.drop_table('ic_decision')
