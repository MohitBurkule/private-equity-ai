"""LLM evals for /ask and schema extraction against the configured provider (LLM_PROVIDER).

Two suites on in-repo synthetic documents (CI-safe) plus, when DATA_DIR is given, FinanceBench
questions on the PDFs in DATA_DIR/sec. Scored by code: the verification gate already rejects
unsupported quotes/numbers, so "wrong" means a verified-but-incorrect answer; "abstain" means not_found.
Usage: python evals/run_llm_eval.py [DATA_DIR] [--n 20]
"""
import hashlib
import json
import re
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from sqlalchemy.orm import Session  # noqa: E402

from app.answer import answer_question  # noqa: E402
from app.citations import numbers_in  # noqa: E402
from app.db import Base, make_engine  # noqa: E402
from app.extract.run import extract_schema  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.models import Document, PageRow  # noqa: E402

FACILITY = ("Facility Agreement (amounts in $ millions)\nTerm Loan A principal amount 250.0 maturing in 2029.\n"
            "Margin 4.25% per annum over SOFR.\nNet leverage shall not exceed 3.50x at any test date.\n"
            "Minimum interest cover [***] to 1.00.\nLargest customer accounted for 42% of revenue.\n")
CASHFLOW = ("Consolidated Statement of Cash Flows (Millions)\nYears ended December 31 2018 2017\n"
            "Net cash provided by operating activities 6,439 6,240\n"
            "Purchases of property, plant and equipment (1,577) (1,373)\n"
            "Proceeds from sale of PP&E and other assets 262 49\n")
ASK = [  # (question, expected number or None = must abstain)
    ("What was 3M capital expenditure (purchases of PP&E) in 2018?", 1577),
    ("What was net cash provided by operating activities in 2017?", 6240),
    ("What was Apple's iPhone unit volume in 2018?", None),
]
EXTRACT = {"debt.principal": 250.0, "debt.margin_pct": 4.25, "debt.maturity_year": 2029,
           "debt.max_net_leverage_x": 3.5, "customers.top1_pct": 42.0}


def _id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _db(pages: dict[str, str]) -> Session:
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    s = Session(e)
    for name, text in pages.items():
        d = Document(id=_id(name), tenant_id="t", sha256=name, filename=name, n_pages=1)
        d.pages = [PageRow(number=1, text=text)]
        s.add(d)
    s.commit()
    return s


def run_ask(llm) -> dict:
    db = _db({"cashflow": CASHFLOW})
    ok, rows = 0, []
    for q, want in ASK:
        t = time.time()
        a = answer_question(db, "t", llm, q)
        nums = {abs(float(n.value)) for c in a.claims for n in numbers_in(c.text)}
        good = (a.status == "not_found") if want is None else (a.status == "answered" and want in nums)
        ok += good
        rows.append({"q": q, "status": a.status, "ok": good, "sec": round(time.time() - t, 1),
                     "claims": [c.text for c in a.claims]})
    return {"suite": "ask", "ok": ok, "total": len(ASK), "rows": rows}


def run_extract(llm) -> dict:
    db = _db({"facility": FACILITY})
    doc = db.get(Document, _id("facility"))
    res = extract_schema(db, "t", llm, doc, "debt", "Acme", "2026")
    res2 = extract_schema(db, "t", llm, doc, "customer_concentration", "Acme", "2026")
    got = {r.metric: r for r in res.results + res2.results}
    ok, rows = 0, []
    for m, want in EXTRACT.items():
        r = got.get(m)
        good = bool(r and r.status == "accepted" and r.value is not None and abs(r.value - Decimal(str(want))) < Decimal("0.001"))
        ok += good
        rows.append({"metric": m, "ok": good, "status": r.status if r else "missing"})
    red = got.get("debt.min_interest_cover_x")  # masked term: must be redacted, never filled
    good = bool(red and red.status == "redacted" and red.value is None)
    ok += good
    rows.append({"metric": "debt.min_interest_cover_x", "ok": good, "status": red.status if red else "missing"})
    return {"suite": "extract", "ok": ok, "total": len(EXTRACT) + 1, "rows": rows}


def run_financebench(llm, data: Path, n: int) -> dict:
    from app.parse.pdf import extract_pages
    gold = [json.loads(x) for x in (data / "financebench_open_source.jsonl").open()]
    have = {p.stem: p for p in (data / "sec").glob("*.pdf")}
    items = [g for g in gold if g["doc_name"] in have and re.fullmatch(r"\$?[\d,.]+", g["answer"].strip())][:n]
    docs = {name: "\n".join(f"\f{p.text}" for p in extract_pages(have[name])) for name in {g["doc_name"] for g in items}}
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    db = Session(e)
    ids = {}
    for name in docs:
        pgs = extract_pages(have[name])
        d = Document(id=_id(name), tenant_id="t", sha256=name, filename=name, n_pages=len(pgs))
        d.pages = [PageRow(number=p.number, text=p.text) for p in pgs]
        db.add(d)
        ids[name] = d.id
    db.commit()
    ok = ab = wrong = 0
    for g in items:
        want = float(g["answer"].replace("$", "").replace(",", ""))
        a = answer_question(db, "t", llm, g["question"], doc_id=ids[g["doc_name"]])
        nums = {abs(float(n.value)) for c in a.claims for n in numbers_in(c.text)}
        if a.status != "answered":
            ab += 1
        elif want in nums:
            ok += 1
        else:
            wrong += 1
    return {"suite": "financebench_numeric", "n": len(items), "correct": ok, "abstained": ab, "verified_wrong": wrong}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 20
    args = [a for a in args if a != str(n)]
    llm = get_llm()
    out = [run_ask(llm), run_extract(llm)]
    if args:
        out.append(run_financebench(llm, Path(args[0]), n))
    print(json.dumps(out, indent=1, default=str))
    sys.exit(0 if all(o.get("ok") == o.get("total") for o in out[:2]) else 1)
