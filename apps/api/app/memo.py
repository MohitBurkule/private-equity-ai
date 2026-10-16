"""IC memo section builder. Every number gets a footnote to document, page, quote.

Derived numbers are computed here in code from cited facts, never by a model.
Only status="verified" facts appear (OCR-sourced and unconfirmed facts are excluded).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.acl import fact_visible
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


def build_memo_data(db: Session, tenant_id: str, entity: str, scope: set[str] | None = None) -> Memo:
    memo = Memo(entity)
    facts = (db.query(Fact).filter_by(tenant_id=tenant_id, entity=entity, status="verified")
             .order_by(Fact.period, Fact.metric).all())
    by_key: dict[tuple[str, str], Fact] = {}
    facts = [f for f in facts if fact_visible(f, scope)]
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


def build_memo(db: Session, tenant_id: str, entity: str, scope: set[str] | None = None) -> str:
    m = build_memo_data(db, tenant_id, entity, scope)
    if m.empty:
        return f"# {entity}\n\nNo verified facts available. Nothing to report.\n"
    out = [f"# {entity}: financial summary (draft, analyst review required)", ""]
    out += [f"- {ln}" for ln in m.lines]
    if m.derived:
        out += ["", "Derived (computed in code):", *[f"- {d}" for d in m.derived]]
    return "\n".join([*out, "", "Sources:", *m.notes]) + "\n"


def build_memo_docx(db: Session, tenant_id: str, entity: str, scope: set[str] | None = None) -> bytes:
    from docx import Document as Docx
    m = build_memo_data(db, tenant_id, entity, scope)
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


def build_memo_pptx(db: Session, tenant_id: str, entity: str, scope: set[str] | None = None) -> bytes:
    """IC deck: title, figures (8 per slide, each with its footnote marker), derived numbers, sources.
    Same verified-only data as the text and Word memo."""
    from pptx import Presentation
    from pptx.util import Pt
    m = build_memo_data(db, tenant_id, entity, scope)
    prs = Presentation()

    def bullets(title: str, items: list[str], size: int = 16):
        sl = prs.slides.add_slide(prs.slide_layouts[1])
        sl.shapes.title.text = title
        tf = sl.placeholders[1].text_frame
        tf.clear()
        for i, t in enumerate(items):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = t
            para.font.size = Pt(size)

    t = prs.slides.add_slide(prs.slide_layouts[0])
    t.shapes.title.text = f"{entity}: financial summary"
    t.placeholders[1].text = "DRAFT. Analyst review required. Only figures whose quote and number were verified against the cited page."
    if m.empty:
        bullets("No verified facts", ["Nothing to report."])
    for i in range(0, len(m.lines), 8):
        bullets("Figures" + (f" ({i // 8 + 1})" if len(m.lines) > 8 else ""), m.lines[i:i + 8])
    if m.derived:
        bullets("Derived (computed in code)", m.derived)
    for i in range(0, len(m.notes), 6):
        bullets("Sources" + (f" ({i // 6 + 1})" if len(m.notes) > 6 else ""), m.notes[i:i + 6], 11)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
