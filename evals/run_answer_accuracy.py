"""Answer-accuracy eval for /ask on FinanceBench numeric questions, with the configured LLM.

Checkpointed: each question's result is appended to CHECKPOINT as soon as it is done, and a rerun
skips finished questions, so a stall or kill loses at most one question. Use --chunk N to stop after
N new questions, so each foreground command stays inside the tool timeout.

Reports:
  exact_numeric_match  share of questions whose answer contains the gold number
  verified_wrong       share answered with a verified claim whose number is wrong
  abstain              share the system declined to answer (not_found); model errors are counted separately
  abstain_when_unsure  of the questions it did not get right, the share it abstained on

Usage: python evals/run_answer_accuracy.py DATA_DIR [--n 50] [--chunk 10] [--checkpoint PATH] [--k 2]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.answer import answer_question
from app.citations import numbers_in
from app.db import Base, make_engine
from app.llm import LlamaCppLLM
from app.models import Document, PageRow
from app.parse.pdf import extract_pages
from run_llm_eval import _id
from sqlalchemy.orm import Session


def _load_items(data: Path, n: int) -> list[dict]:
    gold = [json.loads(x) for x in (data / "financebench_open_source.jsonl").open()]
    have = {p.stem for p in (data / "sec").glob("*.pdf")}
    return [g for g in gold if g["doc_name"] in have and re.fullmatch(r"\$?[\d,.]+", g["answer"].strip())][:n]


def _pages(data: Path, name: str, cache: Path) -> list[tuple[int, str]]:
    """PDF text per page, cached as JSON: extraction of a 10-K takes ~40 s and each chunk is a new process."""
    f = cache / f"{name}.json"
    if f.exists():
        return [tuple(x) for x in json.loads(f.read_text())]
    pgs = [(p.number, p.text) for p in extract_pages(data / "sec" / f"{name}.pdf")]
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(pgs))
    return pgs


def _db(data: Path, items: list[dict], cache: Path) -> Session:
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    db = Session(e)
    for name in sorted({g["doc_name"] for g in items}):
        pgs = _pages(data, name, cache)
        d = Document(id=_id(name), tenant_id="t", sha256=name, filename=name, n_pages=len(pgs))
        d.pages = [PageRow(number=num, text=text) for num, text in pgs]
        db.add(d)
    db.commit()
    return db


def _read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


class _Trimmed:
    """Cuts each <document> body in the prompt to page_chars. Retrieval and the verifier still see full pages,
    so this is a separate setup from the default, and results are labelled with it."""

    def __init__(self, inner, page_chars: int):
        self.inner, self.page_chars = inner, page_chars

    def complete(self, system, prompt):
        cut = re.sub(r"(<document [^>]*>\n)(.*?)(\n</document>)",
                     lambda m: m.group(1) + m.group(2)[: self.page_chars] + m.group(3), prompt, flags=re.S)
        return self.inner.complete(system, cut)


class _Logged:
    """Keeps the model's raw output for the question in progress, so the checkpoint shows what it said."""

    def __init__(self, inner):
        self.inner, self.last = inner, ""

    def complete(self, system, prompt):
        self.last = self.inner.complete(system, prompt)
        return self.last


def run(data: Path, n: int, chunk: int, checkpoint: Path, k: int = 2, ids: set[str] | None = None,
        page_chars: int | None = None) -> dict:
    items = _load_items(data, n)
    done = _read(checkpoint)
    todo = [g for g in items if g["financebench_id"] not in done and (ids is None or g["financebench_id"] in ids)][:chunk]
    if todo:
        db = _db(data, todo, checkpoint.with_suffix(".pages"))  # only this chunk's filings
        base = LlamaCppLLM(max_tokens=512, n_ctx=8192 if k > 2 else 4096)  # room for the JSON; prompt is the top-k pages only
        llm = _Logged(_Trimmed(base, page_chars) if page_chars else base)
        with checkpoint.open("a") as out:
            for g in todo:
                want = float(g["answer"].replace("$", "").replace(",", ""))
                a = answer_question(db, "t", llm, g["question"], doc_id=_id(g["doc_name"]), k=k)
                nums = {abs(float(x.value)) for c in a.claims for x in numbers_in(c.text)}
                row = {"id": g["financebench_id"], "status": a.status,
                       "correct": a.status == "answered" and want in nums,
                       "verified_wrong": a.status == "answered" and want not in nums,
                       "claims": [c.text for c in a.claims],
                       "raw": llm.last[:1500]}
                out.write(json.dumps(row) + "\n")
                out.flush()
                done[row["id"]] = row
    rows = [done[g["financebench_id"]] for g in items if g["financebench_id"] in done]
    total, correct = len(items), sum(r["correct"] for r in rows)
    not_correct = len(rows) - correct
    abstained = sum(r["status"] == "not_found" for r in rows)
    errors = sum(r["status"] == "error" for r in rows)
    return {"suite": "answer_accuracy", "n": total, "done": len(rows), "remaining": total - len(rows),
            "exact_numeric_match": round(correct / len(rows), 3) if rows else None,
            "verified_wrong": round(sum(r["verified_wrong"] for r in rows) / len(rows), 3) if rows else None,
            "abstain": round(abstained / len(rows), 3) if rows else None,
            "errors": errors,
            "abstain_when_unsure": round(abstained / not_correct, 3) if not_correct else None}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--chunk", type=int, default=10)
    ap.add_argument("--checkpoint", type=Path, default=Path("answer_accuracy.checkpoint.jsonl"))
    ap.add_argument("--k", type=int, default=2, help="pages retrieved per question")
    ap.add_argument("--ids", nargs="*", help="only these financebench_ids")
    ap.add_argument("--page-chars", type=int, default=None, help="trim each stored page to this many chars")
    a = ap.parse_args()
    print(json.dumps(run(a.data, a.n, a.chunk, a.checkpoint, a.k, set(a.ids) if a.ids else None, a.page_chars), indent=1))
