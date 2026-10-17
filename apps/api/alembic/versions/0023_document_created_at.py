"""document creation time, backfilled from the upload audit events

Revision ID: 0023
Revises: 0022
"""
import json

import sqlalchemy as sa

from alembic import op

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('document', sa.Column('created_at', sa.String(length=40), nullable=True))
    bind = op.get_bind()
    # Earliest upload event per document. Documents with no upload event stay NULL, which
    # retention reads as unknown age and never purges.
    rows = bind.execute(sa.text(
        "SELECT ts, payload FROM audit_event WHERE action IN ('document.upload') ORDER BY id"
    )).fetchall()
    first: dict[str, str] = {}
    for ts, payload in rows:
        doc_id = json.loads(payload).get("document_id")
        if doc_id:
            first.setdefault(doc_id, ts)
    for doc_id, ts in first.items():
        bind.execute(sa.text("UPDATE document SET created_at = :ts WHERE id = :id AND created_at IS NULL"),
                     {"ts": ts, "id": doc_id})


def downgrade() -> None:
    op.drop_column('document', 'created_at')
