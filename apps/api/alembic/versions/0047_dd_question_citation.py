"""DD answers carry the page (or HTML block) and quote they came from

Revision ID: 0047
Revises: 0046
"""
import sqlalchemy as sa

from alembic import op

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dd_question', sa.Column('page', sa.Integer(), nullable=True))
    op.add_column('dd_question', sa.Column('quote', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('dd_question', 'quote')
    op.drop_column('dd_question', 'page')
