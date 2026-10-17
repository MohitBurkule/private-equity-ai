"""Citation-gate eval: of the answers /ask returns, how many trace every number to a source quote?

For each FinanceBench question, run answer_question with the configured LLM and check every returned
claim independently of the gate:
  - the quote appears on the cited page (whitespace normalised),
  - every number in the claim text appears in that quote,
  - and those numbers also appear on the cited page, not only in the quote.
Reports answered, abstained, claims, traced and untraced. trace_share = traced / claims.
Usage: python evals/run_citation_eval.py DATA_DIR [--n 50]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.answer import answer_question
from app.citations import numbers_in
from app.db import Base, make_engine
from app.llm import get_llm
from app.models import Document, PageRow
from app.parse.pdf import extract_pages
from run_llm_eval import _id
from sqlalchemy.orm import Session


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _nums(text: str) -> set[str]:
    return {str(abs(float(n.value))) for n in numbers_in(text)}


def main(data: Path, n: int) -> dict:
    gold = [json.loads(x) for x in (data / "financebench_open_source.jsonl").open()]
    have = {p.stem: p for p in (data / "sec").glob("*.pdf")}
    items = [g for g in gold if g["doc_name"] in have][:n]
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    db = Session(e)
    pages_by_doc: dict[str, dict[int, str]] = {}
    for name in {g["doc_name"] for g in items}:
        pgs = extract_pages(have[name])
        d = Document(id=_id(name), tenant_id="t", sha256=name, filename=name, n_pages=len(pgs))
        d.pages = [PageRow(number=p.number, text=p.text) for p in pgs]
        db.add(d)
        pages_by_doc[_id(name)] = {p.number: _norm(p.text) for p in pgs}
    db.commit()
    llm = get_llm()
    answered = abstained = claims = traced = 0
    for g in items:
        a = answer_question(db, "t", llm, g["question"], doc_id=_id(g["doc_name"]))
        if a.status != "answered":
            abstained += 1
            continue
        answered += 1
        for c in a.claims:
            claims += 1
            page = pages_by_doc.get(c.doc_id, {}).get(c.page, "")
            quote = _norm(c.quote)
            nums = _nums(c.text)
            traced += bool(quote) and quote in page and nums <= _nums(quote) and nums <= _nums(page)
    return {"suite": "citation_trace", "questions": len(items), "answered": answered, "abstained": abstained,
            "claims": claims, "traced": traced, "untraced": claims - traced,
            "trace_share": round(traced / claims, 3) if claims else None}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 50
    args = [a for a in args if a != str(n)]
    print(json.dumps(main(Path(args[0]), n), indent=1))
