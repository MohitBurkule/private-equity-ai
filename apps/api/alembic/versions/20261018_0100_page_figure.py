"""Figures found on each page, with their positions, so a chart value can cite its figure

Revision ID: 20261018_0100_page_figure
Revises: 20261017_2200_webhook_outbox
"""
import sqlalchemy as sa

from alembic import op

revision = '20261018_0100_page_figure'
down_revision = '20261017_2200_webhook_outbox'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'page_figure',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('left', sa.Float(), nullable=False),
        sa.Column('top', sa.Float(), nullable=False),
        sa.Column('right', sa.Float(), nullable=False),
        sa.Column('bottom', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_page_figure_tenant_id'), 'page_figure', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_page_figure_document_id'), 'page_figure', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_page_figure_document_id'), table_name='page_figure')
    op.drop_index(op.f('ix_page_figure_tenant_id'), table_name='page_figure')
    op.drop_table('page_figure')
