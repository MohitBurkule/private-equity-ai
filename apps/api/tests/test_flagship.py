from decimal import Decimal

from fastapi.testclient import TestClient

from app.flagship import lbo_inputs, lbo_step
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
TXT = b"<html><body><p>Mutual non-disclosure agreement. Governing law: Delaware. The term is two years from the effective date.</p></body></html>"


def steps_of(j):
    return {s["step"]: s for s in j["steps"]}


def test_lbo_inputs_must_be_cited_to_this_document_or_labelled():
    raw = {"ebitda": {"value": "10", "source": {"document_id": "d1", "page": 1, "quote": "x"}},
           "leverage": {"value": "5", "assumption": "sponsor view, not from the CIM"}}
    inputs, assumed = lbo_inputs(raw, "d1")
    assert assumed == ["leverage"] and inputs["ebitda"].value == Decimal(10)
    try:
        lbo_inputs({"ebitda": {"value": "10", "source": {"document_id": "other"}}}, "d1")
        raise AssertionError("expected refusal")
    except ValueError as e:
        assert "this document" in str(e)
    assert lbo_step({}, "d1").status == "skipped"


def test_run_reports_each_step_and_skips_what_it_cannot_do():
    h = new_tenant(c, "fs1")
    up = c.post("/documents", files={"file": ("nda.html", TXT, "text/html")}, headers=h)
    assert up.status_code in (200, 201), up.text
    doc = up.json()["id"]
    j = c.post("/flagship/run", headers=h, json={"document_id": doc, "entity": "Acme", "legal_doc_type": "nda"}).json()
    s = steps_of(j)
    assert s["intake"]["status"] == "ok" and s["extraction"]["status"] == "skipped"
    assert s["legal"]["status"] == "ok" and "red_flags" in s["legal"]["result"]
    assert s["lbo"]["status"] == "skipped" and s["memo"]["status"] == "skipped"  # no verified facts for Acme
    assert c.post("/flagship/run", headers=h, json={"document_id": "nope", "entity": "A"}).status_code == 404
