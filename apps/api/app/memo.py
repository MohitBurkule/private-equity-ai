"""IC memo section builder. Every number gets a footnote to document, page, quote.

Derived numbers are computed here in code from cited facts, never by a model.
Only status="verified" facts appear (OCR-sourced and unconfirmed facts are excluded).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Document, Fact


def _fmt(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"


@dataclass
class Memo:
    entity: str
    lines: list[str] = field(default_factory=list)  # bullet text, includes [n] markers
    derived: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # footnote texts, index = marker - 1

    @property
    def empty(self) -> bool:
        return not self.lines


def build_memo_data(db: Session, tenant_id: str, entity: str) -> Memo:
    memo = Memo(entity)
    facts = (db.query(Fact).filter_by(tenant_id=tenant_id, entity=entity, status="verified")
             .order_by(Fact.period, Fact.metric).all())
    by_key: dict[tuple[str, str], Fact] = {}
    for f in facts:
        by_key[(f.metric, f.period)] = f
        n = len(memo.notes) + 1
        src = f.sources[0]
        doc = db.get(Document, src.document_id)
        memo.notes.append(f'[{n}] {doc.filename if doc else src.document_id[:8]}, p.{src.page}: '
                          f'"{src.quote.strip()}"')
        memo.lines.append(f"{f.metric} ({f.period}, {f.basis}): {_fmt(f.value)} {f.unit} [{n}]")
    for (metric, period), f in by_key.items():
        if metric == "net_income" and ("revenue", period) in by_key:
            rev = by_key[("revenue", period)]
            if rev.value and rev.unit == f.unit:
                memo.derived.append(f"net margin ({period}): {_fmt(f.value / rev.value * 100)}% "
                                    f"= net_income / revenue, computed from cited facts")
    return memo


def build_memo(db: Session, tenant_id: str, entity: str) -> str:
    m = build_memo_data(db, tenant_id, entity)
    if m.empty:
        return f"# {entity}\n\nNo verified facts available. Nothing to report.\n"
    out = [f"# {entity}: financial summary (draft, analyst review required)", ""]
    out += [f"- {ln}" for ln in m.lines]
    if m.derived:
        out += ["", "Derived (computed in code):", *[f"- {d}" for d in m.derived]]
    return "\n".join([*out, "", "Sources:", *m.notes]) + "\n"


def build_memo_docx(db: Session, tenant_id: str, entity: str) -> bytes:
    from docx import Document as Docx
    m = build_memo_data(db, tenant_id, entity)
    d = Docx()
    d.add_heading(f"{entity}: financial summary", level=1)
    d.add_paragraph("DRAFT. Analyst review required before use. Figures below are only those whose "
                    "quote and number were verified against the cited source page.")
    if m.empty:
        d.add_paragraph("No verified facts available. Nothing to report.")
    for ln in m.lines:
        d.add_paragraph(ln, style="List Bullet")
    if m.derived:
        d.add_heading("Derived (computed in code)", level=2)
        for ln in m.derived:
            d.add_paragraph(ln, style="List Bullet")
    if m.notes:
        d.add_heading("Sources", level=2)
        for n in m.notes:
            d.add_paragraph(n)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
