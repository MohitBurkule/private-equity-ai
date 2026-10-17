"""Merge the two heads left on main: the deal wall (#541) and the webhook endpoint both began at firm_stamp

Revision ID: 20261017_2110_heads_merge
Revises: 20261017_2020_deal_wall, 20261017_2100_webhook_endpoint
"""
from alembic import (
    op,  # noqa: F401 - kept so the file reads like the others; a merge has no schema change
)

revision = '20261017_2110_heads_merge'
down_revision = ('20261017_2020_deal_wall', '20261017_2100_webhook_endpoint')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
