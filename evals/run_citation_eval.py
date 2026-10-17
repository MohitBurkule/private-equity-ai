"""Citation-gate eval: of the answers /ask returns, how many trace every number to a source quote?

For each FinanceBench question, run answer_question with the configured LLM and check every returned
claim independently of the gate:
  - the quote appears on the cited page (whitespace normalised),
  - every number in the claim text appears in that quote,
  - and those numbers also appear on the cited page, not only in the quote.
Reports answered, abstained, claims, traced and untraced. trace_share = traced / claims.
Usage: python evals/run_citation_eval.py DATA_DIR [--n 50] [--chunk K] [--checkpoint FILE.jsonl]
Checkpointing: each question's counts are appended to FILE; rerun with the same FILE to resume.
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


def main(data: Path, n: int, chunk: int | None = None, checkpoint: Path | None = None) -> dict:
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
    # One JSONL row per question, written as each finishes, so a killed run resumes where it stopped.
    rows = {}
    if checkpoint and checkpoint.exists():
        rows = {r["question"]: r for r in map(json.loads, checkpoint.open())}
    todo = [g for g in items if g["question"] not in rows]
    if chunk:
        todo = todo[:chunk]
    llm = get_llm()
    for g in todo:
        a = answer_question(db, "t", llm, g["question"], doc_id=_id(g["doc_name"]))
        row = {"question": g["question"], "status": a.status, "claims": 0, "traced": 0}
        if a.status == "answered":
            for c in a.claims:
                row["claims"] += 1
                page = pages_by_doc.get(c.doc_id, {}).get(c.page, "")
                quote = _norm(c.quote)
                nums = _nums(c.text)
                row["traced"] += bool(quote) and quote in page and nums <= _nums(quote) and nums <= _nums(page)
        rows[g["question"]] = row
        if checkpoint:
            with checkpoint.open("a") as f:
                f.write(json.dumps(row) + "\n")
    done = [rows[g["question"]] for g in items if g["question"] in rows]
    answered = sum(r["status"] == "answered" for r in done)
    claims = sum(r["claims"] for r in done)
    traced = sum(r["traced"] for r in done)
    return {"suite": "citation_trace", "questions": len(items), "done": len(done), "remaining": len(items) - len(done),
            "answered": answered, "abstained": len(done) - answered,
            "claims": claims, "traced": traced, "untraced": claims - traced,
            "trace_share": round(traced / claims, 3) if claims else None}


if __name__ == "__main__":
    argv = sys.argv[1:]

    def opt(name, cast, default):
        return cast(argv[argv.index(name) + 1]) if name in argv else default

    n = opt("--n", int, 50)
    chunk = opt("--chunk", int, None)
    checkpoint = opt("--checkpoint", Path, None)
    data = Path(next(a for a in argv if not a.startswith("--") and a not in (str(n), str(chunk), str(checkpoint))))
    print(json.dumps(main(data, n, chunk, checkpoint), indent=1))
