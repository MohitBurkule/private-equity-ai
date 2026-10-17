"""HTML filing text blocks and locator columns on fact sources

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa

from alembic import op

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'html_unit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('document_id', sa.String(length=64), sa.ForeignKey('document.id'), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('section', sa.String(length=32), nullable=True),
        sa.Column('heading', sa.String(length=256), nullable=True),
        sa.Column('anchor', sa.String(length=128), nullable=True),
        sa.Column('offset', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.UniqueConstraint('document_id', 'idx'),
    )
    op.create_index('ix_html_unit_tenant_id', 'html_unit', ['tenant_id'])
    op.create_index('ix_html_unit_document_id', 'html_unit', ['document_id'])
    op.add_column('fact_source', sa.Column('section', sa.String(length=32), nullable=True))
    op.add_column('fact_source', sa.Column('anchor', sa.String(length=128), nullable=True))
    op.add_column('fact_source', sa.Column('offset', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('fact_source', 'offset')
    op.drop_column('fact_source', 'anchor')
    op.drop_column('fact_source', 'section')
    op.drop_index('ix_html_unit_document_id', table_name='html_unit')
    op.drop_index('ix_html_unit_tenant_id', table_name='html_unit')
    op.drop_table('html_unit')
