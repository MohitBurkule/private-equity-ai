"""heading on fact sources, so an HTML citation can be labelled by its section heading

Revision ID: 0029
Revises: 0028
"""
import sqlalchemy as sa

from alembic import op

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fact_source', sa.Column('heading', sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column('fact_source', 'heading')
