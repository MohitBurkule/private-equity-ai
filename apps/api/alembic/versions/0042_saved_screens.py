"""saved strategy screens: named criteria a team reruns against the target list

Revision ID: 0042
Revises: 0041
"""
import sqlalchemy as sa

from alembic import op

revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_screen',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('criteria', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(length=40), nullable=False, server_default=''),
        sa.UniqueConstraint('tenant_id', 'name'),
    )
    op.create_index('ix_saved_screen_tenant_id', 'saved_screen', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_saved_screen_tenant_id', table_name='saved_screen')
    op.drop_table('saved_screen')
