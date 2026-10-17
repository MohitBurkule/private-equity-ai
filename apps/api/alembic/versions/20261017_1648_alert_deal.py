"""alert deal column; existing deal and dd alerts take the deal name from their title

Revision ID: 20261017_1648_alert_deal
Revises: 0057
"""
import sqlalchemy as sa

from alembic import op

revision = '20261017_1648_alert_deal'
down_revision = '0058'
branch_labels = None
depends_on = None

DEAL_KINDS = ("deal", "dd")


def upgrade() -> None:
    op.add_column('alert', sa.Column('deal', sa.String(length=128), nullable=True))
    op.create_index('ix_alert_deal', 'alert', ['deal'])
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, kind, title FROM alert WHERE kind IN ('deal', 'dd')")).fetchall()
    for row_id, kind, title in rows:
        if ": " in title:
            bind.execute(sa.text("UPDATE alert SET deal = :d WHERE id = :i"),
                         {"d": title.split(": ", 1)[0], "i": row_id})


def downgrade() -> None:
    op.drop_index('ix_alert_deal', table_name='alert')
    op.drop_column('alert', 'deal')
