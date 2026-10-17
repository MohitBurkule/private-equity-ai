import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def upload(h, text, deal):
    wb = Workbook()
    wb.active["A1"] = text
    b = io.BytesIO()
    wb.save(b)
    r = c.post("/documents", files={"file": (f"{text}.xlsx", b.getvalue(), "x")}, data={"deal": deal}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_review_lists_only_documents_filed_after_the_latest_decision():
    h = new_tenant(c, "ic-review")
    before = upload(h, "pre-ic-pack", "Acme")
    decision = {"deal": "Acme", "outcome": "hold", "rationale": "wait for QoE", "dissent": "too rich",
                "dissenter": "VP"}
    c.post("/ic/decisions", headers=h, json=decision)
    after = upload(h, "post-ic-revision", "Acme")
    c.post("/ic/decisions", headers=h, json={**decision, "outcome": "proceed", "dissent": None, "dissenter": None})

    r = c.get("/ic/review", params={"deal": "Acme"}, headers=h).json()
    assert r["ic_recorded"] is True
    assert r["latest"]["outcome"] == "proceed"
    assert [d["outcome"] for d in r["dissents"]] == ["hold"]  # the dissent stays on the record of its own decision
    assert before not in [d["document_id"] for d in r["changed_since_ic"]]
    assert after not in [d["document_id"] for d in r["changed_since_ic"]]  # both precede the second decision
    late = upload(h, "filed-after-ic", "Acme")
    r = c.get("/ic/review", params={"deal": "Acme"}, headers=h).json()
    assert [d["document_id"] for d in r["changed_since_ic"]] == [late]


def test_review_without_a_decision_reports_none_and_no_changes():
    h = new_tenant(c, "ic-review2")
    upload(h, "no-decision-yet", "Beta")
    r = c.get("/ic/review", params={"deal": "Beta"}, headers=h).json()
    assert r == {"deal": "Beta", "latest": None, "dissents": [], "changed_since_ic": [], "ic_recorded": False}
