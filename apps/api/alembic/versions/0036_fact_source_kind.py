"""citation kind on fact sources; existing HTML and workbook citations get their real locators

A workbook page used to be a whole sheet and was cited as "p.N". Those pages are still valid, so the
migration keeps them and rewrites each citation as Sheet!Cell, row: label, taken from its quote. HTML
citations (page 0) become kind html.

Revision ID: 0036
Revises: 0035
"""
import re

import sqlalchemy as sa

from alembic import op

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None

_CELL = re.compile(r"^(?P<sheet>.+?)!(?P<cell>[A-Z]{1,3}\d+): ")
_ROW = re.compile(r"\| row: (?P<row>.+)$")


def upgrade() -> None:
    op.add_column('fact_source', sa.Column('kind', sa.String(length=8), nullable=False, server_default='pdf'))
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE fact_source SET kind = 'html' WHERE page = 0"))
    rows = bind.execute(sa.text(
        "SELECT fs.id, fs.quote, fs.heading, fs.anchor FROM fact_source fs "
        "JOIN document d ON d.id = fs.document_id WHERE d.kind = 'xlsx'")).fetchall()
    for fid, quote, heading, anchor in rows:
        m = _CELL.match(quote.strip())
        if m:
            r = _ROW.search(quote)
            sheet, cell, row = m.group('sheet'), m.group('cell'), (r.group('row').strip() if r else None)
        elif heading and anchor:  # KPI workbook citations already carry sheet and cell
            sheet, cell, row = heading, anchor, None
        else:
            continue  # stays a page citation; the sheet number is still a valid page
        bind.execute(sa.text(
            "UPDATE fact_source SET kind = 'xlsx', heading = :h, anchor = :a, section = :s WHERE id = :i"),
            {"h": sheet, "a": cell, "s": row, "i": fid})


def downgrade() -> None:
    op.drop_column('fact_source', 'kind')
