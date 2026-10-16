"""background ingest jobs

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa

from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ingest_job',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('deal', sa.String(length=128), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('scope', sa.Text(), nullable=True),
        sa.Column('key_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=64), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('spool_path', sa.String(length=512), nullable=False),
        sa.Column('created_at', sa.String(length=40), nullable=False),
        sa.Column('updated_at', sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ingest_job_tenant_id'), 'ingest_job', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ingest_job_tenant_id'), table_name='ingest_job')
    op.drop_table('ingest_job')
