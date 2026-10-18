"""End-to-end /ask eval on a fixed document, run offline with a scripted model.

It measures the pipeline the model cannot skip: the citation gate and the abstention path. The model
is replaced by a script, so a pass says the gate holds for each case, not that a live model answers well.
The gate fails the build if any unsupported answer is shown as answered (hallucination rate must be 0) or
if any case lands on the wrong status (accuracy must be 1.0). Questions are our own; no third-party
benchmark data is used, since its licence is unknown.
"""
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.answer import answer_question
from app.db import Base, make_engine
from app.models import Document, PageRow

PAGE = ("Cash Flows (in millions)\n"
        "Purchases of property, plant and equipment (1,577) (1,373)\n"
        "Net sales 32,136 32,765\n")
LINE = "Purchases of property, plant and equipment (1,577) (1,373)"
DOC = "e" * 64


@dataclass(frozen=True)
class Case:
    question: str
    expect: str  # "answered" or "not_found"
    claims: tuple[dict, ...] = ()


CASES = [
    Case("What was FY2018 capex?", "answered",
         ({"text": "Capex was 1,577 million in FY2018.", "doc_id": DOC, "page": 1, "quote": LINE},)),
    Case("What was FY2017 capex?", "answered",
         ({"text": "Capex was 1,373 million in FY2017.", "doc_id": DOC, "page": 1, "quote": LINE},)),
    Case("What was FY2018 net sales?", "answered",
         ({"text": "Net sales were 32,136 million.", "doc_id": DOC, "page": 1, "quote": "Net sales 32,136 32,765"},)),
    # Abstention: the model finds nothing in the document.
    Case("What was the CEO's salary?", "not_found"),
    Case("What was FY2019 capex?", "not_found"),
    # Wrong number on a real line: the gate must catch it.
    Case("What was FY2018 capex?", "not_found",
         ({"text": "Capex was 1,757 million.", "doc_id": DOC, "page": 1, "quote": LINE},)),
    # Invented quote: the model cites text that is not on the page.
    Case("What was revenue?", "not_found",
         ({"text": "Revenue was 5 billion.", "doc_id": DOC, "page": 1, "quote": "Total revenue 5,000"},)),
    # Citation to a document that does not exist.
    Case("What was FY2018 capex?", "not_found",
         ({"text": "Capex was 1,577 million.", "doc_id": "f" * 64, "page": 1, "quote": LINE},)),
]


class Scripted:
    def __init__(self, claims):
        self.raw = json.dumps({"claims": list(claims)})

    def complete(self, system, prompt):
        return self.raw


def _db():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    s = Session(e)
    d = Document(id=DOC, tenant_id="t", sha256="s", filename="co.pdf", n_pages=1)
    d.pages = [PageRow(number=1, text=PAGE)]
    s.add(d)
    s.commit()
    return s


def run_eval() -> dict:
    db = _db()
    results = []
    try:
        for case in CASES:
            a = answer_question(db, "t", Scripted(case.claims), case.question)
            results.append({"question": case.question, "expect": case.expect, "got": a.status})
    finally:
        db.close()
    correct = sum(r["expect"] == r["got"] for r in results)
    should_abstain = [r for r in results if r["expect"] == "not_found"]
    hallucinated = [r for r in should_abstain if r["got"] == "answered"]
    return {"cases": len(results), "accuracy": correct / len(results),
            "hallucination_rate": len(hallucinated) / len(should_abstain), "failures": [r for r in results if r["expect"] != r["got"]]}


def test_ask_eval_gate_holds():
    report = run_eval()
    assert report["hallucination_rate"] == 0.0, report["failures"]
    assert report["accuracy"] == 1.0, report["failures"]


if __name__ == "__main__":
    print(json.dumps(run_eval(), indent=2))
