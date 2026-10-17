"""IC memo versions and comments, stored server side

Revision ID: 0035
Revises: 0034
"""
import sqlalchemy as sa

from alembic import op

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memo_version',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('entity', sa.String(length=200), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(length=40), nullable=False, server_default=''),
        sa.UniqueConstraint('tenant_id', 'entity', 'number'),
    )
    op.create_index('ix_memo_version_tenant_id', 'memo_version', ['tenant_id'])
    op.create_table(
        'memo_comment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('memo_version.id'), nullable=False),
        sa.Column('author', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False, server_default=''),
    )
    op.create_index('ix_memo_comment_tenant_id', 'memo_comment', ['tenant_id'])
    op.create_index('ix_memo_comment_version_id', 'memo_comment', ['version_id'])


def downgrade() -> None:
    op.drop_index('ix_memo_comment_version_id', table_name='memo_comment')
    op.drop_index('ix_memo_comment_tenant_id', table_name='memo_comment')
    op.drop_table('memo_comment')
    op.drop_index('ix_memo_version_tenant_id', table_name='memo_version')
    op.drop_table('memo_version')
