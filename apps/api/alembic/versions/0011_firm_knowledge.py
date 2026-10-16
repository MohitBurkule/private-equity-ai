"""firm knowledge profile

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa

from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'firm_knowledge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_firm_knowledge_tenant_id'), 'firm_knowledge', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_firm_knowledge_key'), 'firm_knowledge', ['key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_firm_knowledge_key'), table_name='firm_knowledge')
    op.drop_index(op.f('ix_firm_knowledge_tenant_id'), table_name='firm_knowledge')
    op.drop_table('firm_knowledge')
