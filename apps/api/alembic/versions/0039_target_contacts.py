"""contacts per target for outreach

Revision ID: 0039
Revises: 0038
"""
import sqlalchemy as sa

from alembic import op

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'target_contact',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('target_id', sa.Integer(), sa.ForeignKey('target.id'), nullable=False),
        sa.Column('email', sa.String(length=256), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.UniqueConstraint('tenant_id', 'target_id', 'email'),
    )
    op.create_index('ix_target_contact_tenant_id', 'target_contact', ['tenant_id'])
    op.create_index('ix_target_contact_target_id', 'target_contact', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_target_contact_target_id', table_name='target_contact')
    op.drop_index('ix_target_contact_tenant_id', table_name='target_contact')
    op.drop_table('target_contact')
