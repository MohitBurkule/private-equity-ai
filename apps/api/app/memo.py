"""IC memo section builder. Every number gets a footnote to document, page, quote.

Derived numbers are computed here in code from cited facts, never by a model.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Document, Fact


def _fmt(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"


def build_memo(db: Session, entity: str) -> str:
    facts = (db.query(Fact).filter_by(entity=entity, status="verified")
             .order_by(Fact.period, Fact.metric).all())
    if not facts:
        return f"# {entity}\n\nNo verified facts available. Nothing to report.\n"
    lines = [f"# {entity}: financial summary (draft, analyst review required)", ""]
    notes: list[str] = []
    by_key: dict[tuple[str, str], Fact] = {}
    for f in facts:
        by_key[(f.metric, f.period)] = f
        n = len(notes) + 1
        src = f.sources[0]
        doc = db.get(Document, src.document_id)
        notes.append(f'[{n}] {doc.filename if doc else src.document_id[:8]}, p.{src.page}: "{src.quote.strip()}"')
        lines.append(f"- {f.metric} ({f.period}, {f.basis}): {_fmt(f.value)} {f.unit} [{n}]")
    derived = []
    for (metric, period), f in by_key.items():
        if metric == "net_income" and ("revenue", period) in by_key:
            rev = by_key[("revenue", period)]
            if rev.value and rev.unit == f.unit:
                derived.append(f"- net margin ({period}): {_fmt(f.value / rev.value * 100)}% "
                               f"= net_income / revenue, computed from cited facts")
    if derived:
        lines += ["", "Derived (computed in code):", *derived]
    return "\n".join(lines + ["", "Sources:", *notes]) + "\n"
