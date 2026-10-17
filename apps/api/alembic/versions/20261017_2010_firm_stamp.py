"""Stamp firm knowledge rows with the prompt version and the provider and model that wrote them

Revision ID: 20261017_2010_firm_stamp
Revises: 20261017_2000_answer_cache
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_2010_firm_stamp'
down_revision = '20261017_2000_answer_cache'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('firm_knowledge', sa.Column('prompt_version', sa.String(length=32), server_default='', nullable=False))
    op.add_column('firm_knowledge', sa.Column('model', sa.String(length=128), server_default='', nullable=False))


def downgrade() -> None:
    op.drop_column('firm_knowledge', 'model')
    op.drop_column('firm_knowledge', 'prompt_version')
