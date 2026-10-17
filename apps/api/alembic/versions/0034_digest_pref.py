"""per-person alert digest preferences, keyed on the OIDC subject

Revision ID: 0034
Revises: 0033
"""
import sqlalchemy as sa

from alembic import op

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'digest_pref',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('subject', sa.String(length=128), nullable=False),
        sa.Column('email', sa.String(length=256), nullable=False),
        sa.Column('min_severity', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('last_alert_id', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('tenant_id', 'subject'),
    )
    op.create_index('ix_digest_pref_tenant_id', 'digest_pref', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_digest_pref_tenant_id', table_name='digest_pref')
    op.drop_table('digest_pref')
