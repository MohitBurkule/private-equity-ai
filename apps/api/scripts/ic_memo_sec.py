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

TAGS = {  # metric -> us-gaap tags, first tag with data wins
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "net_income": ("NetIncomeLoss",),
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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ic_memo_sec.py <cik> <out.pptx>", file=sys.stderr)
        return 2
    cik, out = argv
    if not os.environ.get("SEC_USER_AGENT"):
        print("set SEC_USER_AGENT", file=sys.stderr)
        return 2
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/ic.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy.orm import sessionmaker

    from app import edgar
    from app.db import Base, make_engine
    from app.facts import add_verified_fact
    from app.ingest import _store_pages
    from app.memo import build_memo_pptx
    from app.parse.office import RawPage
    from app.rls import bind_tenant

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
    engine = make_engine()
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        bind_tenant(db, TENANT)
        doc = _store_pages(db, TENANT, json.dumps(raw).encode(), f"{cik}_companyfacts.json", "sec_companyfacts",
                           pages)
        number_by_line = {}
        for n, (end, v) in enumerate(sorted(lines_by_year.items()), start=1):
            for line in v:
                number_by_line[line] = n
        for metric, rs in rows.items():
            for r in rs:
                line = next(x for x in number_by_line if x.startswith(f"{metric} for fiscal year ending {r['end']}:"))
                add_verified_fact(db, tenant_id=TENANT, entity=entity, metric=metric,
                                  period=f"FY{r['end'][:4]}", value=Decimal(str(r["val"])), unit="USD",
                                  document_id=doc.id, page=number_by_line[line], quote=line)
        Path(out).write_bytes(build_memo_pptx(db, TENANT, entity))
        print(f"{entity}: {sum(len(v) for v in rows.values())} figures cited -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
