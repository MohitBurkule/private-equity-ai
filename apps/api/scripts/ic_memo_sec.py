"""End-to-end IC memo for one SEC company, every number cited.

Fetch companyfacts (10-K annual values), write them as a text source document (one page per fiscal year,
each line quoting the figure verbatim), store that document, verify each figure as a fact through the
normal citation check, then build the IC deck with build_memo_pptx.

Usage (from apps/api): SEC_USER_AGENT="name email" DATABASE_URL=... python scripts/ic_memo_sec.py <cik> <out.pptx>
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

TAGS = {  # metric -> us-gaap tags, earlier tags win per period
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "total_assets": ("Assets",),
}
TENANT = "ic-demo"
YEARS = 3


def annual(facts: dict, tags: tuple[str, ...]) -> list[dict]:
    """Latest full-year 10-K value per period end. Tags are merged in order: a later tag only fills
    period ends the earlier tags do not report, so a company that changed its revenue tag keeps every year."""
    by_end: dict[str, dict] = {}
    for tag in tags:
        rows = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
        for r in rows:
            if r.get("form") != "10-K" or r.get("fp") != "FY" or not r.get("end"):
                continue
            if r["end"] not in by_end or (tag == tags[0] and by_end[r["end"]].get("_tag") != tags[0]) or (
                    by_end[r["end"]].get("_tag") == tag and r.get("filed", "") > by_end[r["end"]].get("filed", "")):
                by_end[r["end"]] = {**r, "_tag": tag}
    return sorted(by_end.values(), key=lambda r: r["end"])[-YEARS:]


def ingest(db, cik: str, edgar, store_pages, add_verified_fact, Decimal) -> str:
    """Store one company's 10-K annual figures as a cited source and verify each as a fact. Returns entity name."""
    from app.parse.office import RawPage

    raw = edgar.fetch_companyfacts(cik)
    entity = raw.get("entityName") or cik
    rows = {m: annual(raw, tags) for m, tags in TAGS.items()}
    lines_by_year: dict[str, list[str]] = {}
    for metric, rs in rows.items():
        for r in rs:
            line = (f"{metric} for fiscal year ending {r['end']}: {int(r['val'])} USD "
                    f"(SEC companyfacts, 10-K accession {r['accn']}).")
            lines_by_year.setdefault(r["end"], []).append(line)
    pages = [RawPage("\n".join(v)) for _, v in sorted(lines_by_year.items())]
    doc = store_pages(db, TENANT, json.dumps(raw).encode(), f"{cik}_companyfacts.json", "sec_companyfacts", pages)
    page_of = {line: n for n, (_, v) in enumerate(sorted(lines_by_year.items()), start=1) for line in v}
    for metric, rs in rows.items():
        for r in rs:
            prefix = f"{metric} for fiscal year ending {r['end']}:"
            line = next(x for x in page_of if x.startswith(prefix))
            add_verified_fact(db, tenant_id=TENANT, entity=entity, metric=metric, period=f"FY{r['end'][:4]}",
                              value=Decimal(str(r["val"])), unit="USD", document_id=doc.id,
                              page=page_of[line], quote=line)
    return entity


def peer_slide(prs, db, peers: list[str], build_memo_data, Pt) -> None:
    """Peer table: latest revenue and net income per peer, each with its own source note."""
    from pptx.util import Inches

    sl = prs.slides.add_slide(prs.slide_layouts[5])
    sl.shapes.title.text = "Peers (cited figures, latest year)"
    lines, notes = [], []
    for k, name in enumerate(peers, start=1):
        m = build_memo_data(db, TENANT, name)  # each peer keeps its own note numbers, prefixed P<k>
        rev = m.series.get("revenue", [])
        ni = m.series.get("net_income", [])
        if not rev:
            lines.append(f"{name}: no verified revenue")
            continue
        per, val, n = rev[-1]
        notes.append(f"P{k}-{n} {name} {per} revenue: " + m.notes[n - 1].split(": ", 1)[-1])
        ni_txt = f", net income {_money(ni[-1][1])} [P{k}-{ni[-1][2]}]" if ni and ni[-1][0] == per else ""
        lines.append(f"{name} ({per}): revenue {_money(val)} [P{k}-{n}]{ni_txt}")
    tf = sl.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(2.5)).text_frame
    tf.word_wrap = True
    for i, t in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = t
        para.font.size = Pt(14)
    if notes:
        sl2 = prs.slides.add_slide(prs.slide_layouts[5])
        sl2.shapes.title.text = "Peer sources"
        tf2 = sl2.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(5)).text_frame
        tf2.word_wrap = True
        for i, t in enumerate(notes):
            para = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            para.text = t
            para.font.size = Pt(11)


def _money(v) -> str:
    return f"{float(v) / 1e6:,.1f}M USD"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: ic_memo_sec.py <cik> <out.pptx> [peer_cik ...]", file=sys.stderr)
        return 2
    cik, out, peer_ciks = argv[0], argv[1], argv[2:]
    if not os.environ.get("SEC_USER_AGENT"):
        print("set SEC_USER_AGENT", file=sys.stderr)
        return 2
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/ic.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from io import BytesIO

    from pptx import Presentation
    from pptx.util import Pt
    from sqlalchemy.orm import sessionmaker

    from app import edgar
    from app.db import Base, make_engine
    from app.facts import add_verified_fact
    from app.ingest import _store_pages
    from app.memo import build_memo_data, build_memo_pptx
    from app.rls import bind_tenant

    engine = make_engine()
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        bind_tenant(db, TENANT)
        entity = ingest(db, cik, edgar, _store_pages, add_verified_fact, Decimal)
        peer_names = [ingest(db, pc, edgar, _store_pages, add_verified_fact, Decimal) for pc in peer_ciks]
        data = build_memo_pptx(db, TENANT, entity)
        if peer_names:
            prs = Presentation(BytesIO(data))
            peer_slide(prs, db, peer_names, build_memo_data, Pt)
            buf = BytesIO()
            prs.save(buf)
            data = buf.getvalue()
        Path(out).write_bytes(data)
        print(f"{entity}: deck with {len(peer_names)} peers -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
