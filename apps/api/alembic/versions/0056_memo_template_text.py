"""firm heading text and intro line for memo templates

Revision ID: 0056
Revises: 0055
"""
import sqlalchemy as sa

from alembic import op

revision = '0056'
down_revision = '0055'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('memo_template', sa.Column('headings', sa.Text(), nullable=False, server_default='{}'))
    op.add_column('memo_template', sa.Column('intro', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('memo_template', 'intro')
    op.drop_column('memo_template', 'headings')
