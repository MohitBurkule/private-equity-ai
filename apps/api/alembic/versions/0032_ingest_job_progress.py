"""per-file progress on background ingest jobs

Revision ID: 0032
Revises: 0031
"""
import sqlalchemy as sa

from alembic import op

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ingest_job', sa.Column('files_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('ingest_job', sa.Column('files_done', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('ingest_job', sa.Column('current_file', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('ingest_job', 'current_file')
    op.drop_column('ingest_job', 'files_done')
    op.drop_column('ingest_job', 'files_total')
