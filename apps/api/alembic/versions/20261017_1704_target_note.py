"""target notes

Revision ID: 20261017_1704_target_note
Revises: 0059
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1704_target_note'
down_revision = '0059'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'target_note',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('author', sa.String(length=64), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.Column('edited_at', sa.String(length=40), nullable=False),
    )
    op.create_index('ix_target_note_tenant_id', 'target_note', ['tenant_id'])
    op.create_index('ix_target_note_target_id', 'target_note', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_target_note_target_id', table_name='target_note')
    op.drop_index('ix_target_note_tenant_id', table_name='target_note')
    op.drop_table('target_note')
