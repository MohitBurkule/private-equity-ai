"""KPI kind: budget figures are cited observations too, kept apart from actuals so both can be compared

Revision ID: 20261017_1725_kpi_kind
Revises: 0059
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1725_kpi_kind'
down_revision = '20261017_1704_target_note'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing observations are actuals: the server default backfills them.
    op.add_column('kpi_observation', sa.Column('kind', sa.String(16), nullable=False, server_default='actual'))


def downgrade() -> None:
    op.drop_column('kpi_observation', 'kind')
