"""Target research note (Word): one page per target built only from stored records and their source links.

Sections: identity and where it came from, revenue with its filing link (or "not stated"), sector benchmark,
prior mentions across the firm's own records, and a Sources list. Nothing is estimated: a missing field is
written as "not stated in the record", so a reader can see the gap instead of a made-up value.
"""
from __future__ import annotations

import io

from sqlalchemy.orm import Session

from app import seen_before as seen_mod
from app import targets as tg_mod
from app.models import Target


def _none(v) -> str:
    return "not stated in the record" if v in (None, "") else str(v)


def _sections(db: Session, tenant: str, t: Target, scope_deals: set[str] | None) -> list[tuple[str, list[str]]]:
    """Ordered (heading, lines) pairs. The Word and slide renderers both read this, so they never disagree."""
    out: list[tuple[str, list[str]]] = []
    out.append(("Identity", [f"{label}: {_none(val)}" for label, val in (
        ("Source", t.source), ("Source reference", t.source_ref), ("Sector", t.sector),
        ("SIC", t.sic), ("Country", t.country), ("Region", t.region), ("Pipeline status", t.status))]))

    if t.revenue is None:
        rev = ["Revenue: not stated in the record. No estimate is shown."]
    else:
        money = " ".join(x for x in (t.currency, str(t.revenue)) if x)
        rev = [f"Revenue: {money} for {_none(t.revenue_period)}.", f"Filing: {_none(t.revenue_url)}"]
    out.append(("Revenue", rev))

    b = tg_mod.benchmark(db, tenant, t.sector.split(" (")[0] if t.sector else None, t)
    if b["peers"] == 0:
        bench = ["No peers with stated revenue in this sector. No benchmark shown."]
    else:
        bench = [(f"{b['peers']} peer(s) with stated revenue, not counting this target; "
                  f"{b['excluded_no_revenue']} excluded for no revenue."),
                 f"Median {b['median']}; interquartile {b['q1']} to {b['q3']}."]
        if "target" in b:
            bench.append(f"This target sits at percentile {b['target']['percentile']} among those peers.")
    out.append(("Sector benchmark", bench))

    hits = seen_mod.lookup(db, tenant, t.name, scope_deals)["hits"]
    others = [h for h in hits if not (h["kind"] == "target" and h["id"] == t.id)]
    if others:
        prior = [f"{h['kind'].replace('_', ' ')}: {h['name']} ({h['rule']} name match)" for h in others]
    else:
        prior = ["No other matching record. This may be a first look; confirm by name variants."]
    out.append(("Prior mentions in firm records", prior))

    srcs = [f"Target record: {t.source}:{t.source_ref} {t.source_url or ''}".strip()]
    if t.revenue_url:
        srcs.append(f"Revenue filing: {t.revenue_period or 'period not stated'} {t.revenue_url}")
    out.append(("Sources", srcs))
    return out


def build_docx(db: Session, tenant: str, t: Target, scope_deals: set[str] | None) -> bytes:
    from docx import Document as Docx

    d = Docx()
    d.add_heading(t.name, level=1)
    d.add_paragraph("DRAFT research note. Built from stored records only; each figure links to its source.")
    for heading, lines in _sections(db, tenant, t, scope_deals):
        d.add_heading(heading, level=2)
        for line in lines:
            d.add_paragraph(line, style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def build_pptx(db: Session, tenant: str, t: Target, scope_deals: set[str] | None) -> bytes:
    """Same sections as the Word note, one slide each. Title slide carries the DRAFT line."""
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = f"Research: {t.name}"
    s.placeholders[1].text = "DRAFT · built from stored records only; each figure links to its source"
    for heading, lines in _sections(db, tenant, t, scope_deals):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = heading
        tf = s.placeholders[1].text_frame
        tf.clear()
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = line
            p.font.size = Pt(16)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
