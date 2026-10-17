"""Trading comps and precedent transactions from cited, verified facts.

Each comp is an entity with an enterprise value and one or more denominators (revenue, ebitda, ...) for a
stated period. A multiple is computed only when both facts exist, share a unit, and the denominator is
positive; otherwise it is reported as not meaningful with the reason, never defaulted. Statistics skip those
rows. The implied range for a target is target metric x (quartile 1, median, quartile 3) of the peer multiples,
with every input fact id returned. Fewer than MIN_PEERS usable multiples gives no range.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.calc import _find
from app.citations import locator_label
from app.models import Fact

MIN_PEERS = 3
EV_METRIC = "enterprise_value"


@dataclass
class Row:
    entity: str
    multiples: dict[str, Decimal | None] = field(default_factory=dict)
    nm: dict[str, str] = field(default_factory=dict)  # metric -> reason not meaningful
    facts: dict[str, int] = field(default_factory=dict)  # role -> fact id


@dataclass
class Stats:
    n: int
    low: Decimal | None = None
    q1: Decimal | None = None
    median: Decimal | None = None
    mean: Decimal | None = None
    q3: Decimal | None = None
    high: Decimal | None = None


@dataclass
class Implied:
    metric: str
    target_value: Decimal
    multiple: str
    low: Decimal | None
    mid: Decimal | None
    high: Decimal | None
    note: str = ""


def _quantile(vals: list[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between closest ranks (same as numpy default)."""
    s = sorted(vals)
    pos = (len(s) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def stats(vals: list[Decimal]) -> Stats:
    if not vals:
        return Stats(0)
    return Stats(len(vals), min(vals), _quantile(vals, Decimal("0.25")), _quantile(vals, Decimal("0.5")),
                 sum(vals, Decimal(0)) / len(vals), _quantile(vals, Decimal("0.75")), max(vals))


def multiple(ev: Decimal, denom: Decimal) -> tuple[Decimal | None, str]:
    if denom <= 0:
        return None, "denominator not positive"
    if ev <= 0:
        return None, "enterprise value not positive"
    return ev / denom, ""


def implied_range(metric: str, target_value: Decimal, st: Stats) -> Implied:
    label = f"EV/{metric}"
    if target_value <= 0:
        return Implied(metric, target_value, label, None, None, None, "target metric not positive")
    if st.n < MIN_PEERS:
        return Implied(metric, target_value, label, None, None, None,
                       f"only {st.n} usable multiples, need {MIN_PEERS}")
    return Implied(metric, target_value, label, target_value * st.q1, target_value * st.median,
                   target_value * st.q3)


def build_rows(db: Session, tenant: str, entities: list[str], period: str, metrics: list[str],
               scope: set[str] | None, ev_period: str | None = None) -> list[Row]:
    rows = []
    for ent in entities:
        r = Row(ent)
        ev = _find(db, tenant, ent, EV_METRIC, ev_period or period, scope)
        if ev is not None:
            r.facts["enterprise_value"] = ev.id
        for m in metrics:
            d = _find(db, tenant, ent, m, period, scope)
            if ev is None or d is None:
                r.multiples[m], r.nm[m] = None, ("no enterprise value fact" if ev is None
                                                 else f"no {m} fact for {period}")
                continue
            r.facts[m] = d.id
            if ev.unit != d.unit:
                r.multiples[m], r.nm[m] = None, f"unit mismatch {ev.unit} vs {d.unit}"
                continue
            r.multiples[m], r.nm[m] = multiple(ev.value, d.value)
            if r.multiples[m] is not None:
                r.nm.pop(m)
        rows.append(r)
    return rows


def run(db: Session, tenant: str, target: str, entities: list[str], period: str, metrics: list[str],
        scope: set[str] | None, target_period: str | None = None, ev_period: str | None = None) -> dict:
    rows = build_rows(db, tenant, [e for e in entities if e != target], period, metrics, scope, ev_period)
    out = {"target": target, "period": period, "peers": [], "stats": {}, "implied": []}
    for m in metrics:
        st = stats([r.multiples[m] for r in rows if r.multiples.get(m) is not None])
        out["stats"][m] = {k: (v if k == "n" or v is None else str(v)) for k, v in st.__dict__.items()}
        t = _find(db, tenant, target, m, target_period or period, scope)
        if t is None:
            out["implied"].append({"metric": m, "multiple": f"EV/{m}", "target_fact_id": None,
                                   "note": f"no {m} fact for {target}"})
            continue
        im = implied_range(m, t.value, st)
        out["implied"].append({"metric": m, "multiple": im.multiple, "target_fact_id": t.id,
                               "target_value": str(t.value), "unit": t.unit, "note": im.note,
                               **{k: None if getattr(im, k) is None else str(getattr(im, k))
                                  for k in ("low", "mid", "high")}})
    for r in rows:
        out["peers"].append({"entity": r.entity, "facts": r.facts, "nm": r.nm,
                             "multiples": {k: None if v is None else str(v.quantize(Decimal("0.01")))
                                           for k, v in r.multiples.items()}})
    return out


__all__ = ["Fact", "implied_range", "multiple", "run", "stats"]


def _cite(db: Session, fact_id: int | None) -> str:
    f = db.get(Fact, fact_id) if fact_id else None
    if f is None or not f.sources:
        return "no source"
    return "; ".join(f"doc {s.document_id[:8]} {locator_label(s.page, s.section, s.heading)}" for s in f.sources)


def to_docx(db: Session, result: dict) -> bytes:
    """Valuation-range note from a `run` result. Every multiple lists the facts behind it; ranges say when absent."""
    import io

    from docx import Document as Docx
    d = Docx()
    d.add_heading(f"Comparable companies: {result['target']} ({result['period']})", level=1)
    d.add_paragraph("DRAFT. Multiples are computed in code from verified, cited facts. Peers with a missing or "
                    "non-positive input are shown as not meaningful and excluded from the statistics.")
    d.add_heading("Implied valuation", level=2)
    for im in result["implied"]:
        if im.get("mid"):
            d.add_paragraph(f"{im['multiple']}: {im['low']} to {im['high']} {im.get('unit') or ''} "
                            f"(median-based {im['mid']}); target input: {_cite(db, im.get('target_fact_id'))}",
                            style="List Bullet")
        else:
            d.add_paragraph(f"{im['multiple']}: no range ({im.get('note') or 'insufficient data'})",
                            style="List Bullet")
    d.add_heading("Peers", level=2)
    for p in result["peers"]:
        parts = []
        for m, v in p["multiples"].items():
            parts.append(f"EV/{m} {v}" if v else f"EV/{m} n.m. ({p['nm'].get(m, 'unavailable')})")
        srcs = ", ".join(f"{k}: {_cite(db, fid)}" for k, fid in p["facts"].items())
        d.add_paragraph(f"{p['entity']}: " + "; ".join(parts) + (f" [{srcs}]" if srcs else ""),
                        style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pptx(db: Session, result: dict) -> bytes:
    """One slide per topic: implied ranges, then peer multiples. Each figure carries its source line."""
    import io

    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = f"Comparable companies: {result['target']}"
    s.placeholders[1].text = f"{result['period']} · DRAFT · every multiple computed from cited facts"

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Implied valuation"
    tf = s.placeholders[1].text_frame
    tf.clear()
    for i, im in enumerate(result["implied"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if im.get("mid"):
            p.text = f"{im['multiple']}: {im['low']} to {im['high']} (median {im['mid']}) · {_cite(db, im.get('target_fact_id'))}"
        else:
            p.text = f"{im['multiple']}: no range ({im.get('note') or 'insufficient data'})"
        p.font.size = Pt(16)

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Peers"
    tf = s.placeholders[1].text_frame
    tf.clear()
    for i, p_row in enumerate(result["peers"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        parts = [f"EV/{m} {v}" if v else f"EV/{m} n.m. ({p_row['nm'].get(m, 'unavailable')})"
                 for m, v in p_row["multiples"].items()]
        p.text = f"{p_row['entity']}: " + "; ".join(parts)
        p.font.size = Pt(14)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
