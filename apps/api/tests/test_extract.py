import io
import json

from docx import Document as Docx
from fastapi.testclient import TestClient

from app.llm import LLM
from app.main import app, llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)
LINES = ["Facility Agreement (amounts in $ millions)",
         "Term Loan A principal amount 250.0 maturing in 2029.",
         "Margin 4.25% per annum over SOFR.",
         "Net leverage shall not exceed 3.50x at any test date.",
         "Minimum interest cover [***] to 1.00.",
         "Largest customer accounted for 42% of revenue."]


def upload(h):
    d = Docx()
    for ln in LINES:
        d.add_paragraph(ln)
    b = io.BytesIO()
    d.save(b)
    return c.post("/documents", files={"file": ("fa.docx", b.getvalue(), "x")}, headers=h).json()["id"]


class Fake(LLM):
    def __init__(self, fields):
        self.fields = fields

    def complete(self, system, prompt):
        assert "untrusted" in system
        return "Sure:\n" + json.dumps({"fields": self.fields})


def run(h, doc, fields, schema="debt"):
    app.dependency_overrides[llm_dependency] = lambda: Fake(fields)
    try:
        return c.post(f"/documents/{doc}/extract", headers=h,
                      json={"schema_name": schema, "entity": "Acme", "period": "2026"})
    finally:
        app.dependency_overrides.pop(llm_dependency)


def by(r):
    return {f["metric"]: f for f in r.json()["fields"]}


def test_accepts_only_verified_values_flags_redaction_and_lies():
    h = new_tenant(c, "ex1")
    doc = upload(h)
    r = run(h, doc, [
        {"metric": "debt.principal", "value": 250000000, "page": 1, "quote": "principal amount 250.0"},
        {"metric": "debt.margin_pct", "value": 4.25, "page": 1, "quote": "Margin 4.25% per annum"},
        {"metric": "debt.max_net_leverage_x", "value": 3.0, "page": 1, "quote": "shall not exceed 3.50x"},
        {"metric": "debt.min_interest_cover_x", "value": 2.0, "page": 1, "quote": "Minimum interest cover [***] to 1.00"},
        {"metric": "debt.maturity_year", "value": 2029, "page": 1, "quote": "invented quote"},
        {"metric": "debt.bogus", "value": 1, "page": 1, "quote": "x"},
    ])
    f = by(r)
    assert f["debt.principal"]["status"] == "accepted"
    assert f["debt.margin_pct"]["status"] == "accepted"
    assert f["debt.max_net_leverage_x"]["status"] == "rejected"  # 3.0 is not printed
    assert f["debt.min_interest_cover_x"]["status"] == "rejected"  # masked quote, value given
    assert f["debt.maturity_year"]["reason"] == "quote not found on cited page"
    assert f["debt.bogus"]["status"] == "rejected"
    facts = c.get("/facts", headers=h).json()
    assert {x["metric"] for x in facts} == {"debt.principal", "debt.margin_pct"}
    assert all(x["status"] == "auto" for x in facts)
    assert "No verified facts" in c.get("/memo", params={"entity": "Acme"}, headers=h).json()["markdown"]


def test_redacted_terms_reported_not_filled_and_auto_facts_wait_for_review():
    h = new_tenant(c, "ex2")
    doc = upload(h)
    r = run(h, doc, [{"metric": "debt.min_interest_cover_x", "value": None, "redacted": True, "page": 1,
                      "quote": "Minimum interest cover [***] to 1.00"},
                     {"metric": "debt.principal", "value": 250000000, "page": 1, "quote": "principal amount 250.0"}])
    f = by(r)
    assert f["debt.min_interest_cover_x"]["status"] == "redacted" and f["debt.min_interest_cover_x"]["value"] is None
    assert f["debt.maturity_year"]["status"] == "not_found"
    assert "No verified facts" in c.get("/memo", params={"entity": "Acme"}, headers=h).json()["markdown"]
    fid = f["debt.principal"]["fact_id"]
    c.post(f"/facts/{fid}/review", headers=h, json={"action": "accept"})
    assert "debt.principal" in c.get("/memo", params={"entity": "Acme"}, headers=h).json()["markdown"]


def test_false_redaction_claim_and_wrong_scale_rejected():
    h = new_tenant(c, "ex3")
    doc = upload(h)
    r = run(h, doc, [{"metric": "debt.margin_pct", "value": None, "redacted": True, "page": 1,
                      "quote": "Margin 4.25% per annum"},
                     {"metric": "debt.principal", "value": 250000, "page": 1, "quote": "principal amount 250.0"}])
    f = by(r)
    assert f["debt.margin_pct"]["status"] == "rejected" and "no masking" in f["debt.margin_pct"]["reason"]
    assert f["debt.principal"]["status"] == "rejected"  # 250,000 matches neither 250.0 nor 250.0 x 1,000,000


def test_garbage_model_output_schema_list_and_walls():
    h = new_tenant(c, "ex4")
    doc = upload(h)

    class Junk(LLM):
        def complete(self, s, p):
            return "no json here"
    app.dependency_overrides[llm_dependency] = lambda: Junk()
    try:
        r = c.post(f"/documents/{doc}/extract", headers=h, json={"schema_name": "debt", "entity": "A", "period": "1"})
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert r.status_code == 200 and "unusable" in r.json()["detail"] and all(
        f["status"] == "not_found" for f in r.json()["fields"])
    assert "debt" in c.get("/extract/schemas", headers=h).json()
    assert run(h, doc, [], schema="nope").status_code == 422
    other = new_tenant(c, "ex5")
    assert run(other, doc, []).status_code == 404
