"""acquisition targets"""
import sqlalchemy as sa

from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'target',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('source_ref', sa.String(length=64), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('sector', sa.String(length=128), nullable=True),
        sa.Column('sic', sa.String(length=8), nullable=True),
        sa.Column('country', sa.String(length=64), nullable=True),
        sa.Column('region', sa.String(length=64), nullable=True),
        sa.Column('lat', sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column('lng', sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column('revenue', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('revenue_period', sa.String(length=32), nullable=True),
        sa.Column('revenue_url', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'source', 'source_ref'),
    )
    op.create_index(op.f('ix_target_tenant_id'), 'target', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_target_sector'), 'target', ['sector'], unique=False)
    op.create_index(op.f('ix_target_country'), 'target', ['country'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_target_country'), table_name='target')
    op.drop_index(op.f('ix_target_sector'), table_name='target')
    op.drop_index(op.f('ix_target_tenant_id'), table_name='target')
    op.drop_table('target')
