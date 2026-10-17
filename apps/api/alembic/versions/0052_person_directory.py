"""Expert and contact directory, tied to a deal when sourced for one

Revision ID: 0052
Revises: 0051
"""
import sqlalchemy as sa

from alembic import op

revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'person',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('organisation', sa.String(length=200), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('expertise', sa.Text(), nullable=True),
        sa.Column('deal', sa.String(length=128), nullable=True),
        sa.Column('recorded_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_person_tenant_id', 'person', ['tenant_id'])
    op.create_index('ix_person_deal', 'person', ['deal'])


def downgrade():
    op.drop_index('ix_person_deal', table_name='person')
    op.drop_index('ix_person_tenant_id', table_name='person')
    op.drop_table('person')
