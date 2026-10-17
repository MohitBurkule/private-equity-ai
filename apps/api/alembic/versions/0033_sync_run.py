"""connector sync runs: what each sync pulled, and which run brought in each document

Revision ID: 0033
Revises: 0032
"""
import sqlalchemy as sa

from alembic import op

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sync_run',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('connector', sa.String(length=32), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('deal', sa.String(length=128), nullable=True),
        sa.Column('started_at', sa.String(length=40), nullable=False),
        sa.Column('finished_at', sa.String(length=40), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='running'),
        sa.Column('ingested', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unchanged', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
    )
    op.create_index('ix_sync_run_tenant_id', 'sync_run', ['tenant_id'])
    op.create_index('ix_sync_run_deal', 'sync_run', ['deal'])
    op.add_column('document_source', sa.Column('sync_run_id', sa.Integer(), nullable=True))
    op.create_index('ix_document_source_sync_run_id', 'document_source', ['sync_run_id'])
    op.create_foreign_key('fk_document_source_sync_run', 'document_source', 'sync_run', ['sync_run_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_document_source_sync_run', 'document_source', type_='foreignkey')
    op.drop_index('ix_document_source_sync_run_id', table_name='document_source')
    op.drop_column('document_source', 'sync_run_id')
    op.drop_index('ix_sync_run_deal', table_name='sync_run')
    op.drop_index('ix_sync_run_tenant_id', table_name='sync_run')
    op.drop_table('sync_run')
