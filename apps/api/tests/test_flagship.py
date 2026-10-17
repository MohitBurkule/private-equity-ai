from decimal import Decimal

from app.flagship import lbo_inputs, lbo_step
from app.main import app
from fastapi.testclient import TestClient

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


def test_ebitda_is_operating_income_plus_da_from_verified_extraction():
    from app.flagship import Step, derive_ebitda
    ext = Step("extraction", "ok", result={"created": [
        {"metric": "operating_income", "value": "1000", "page": 3, "quote": "Operating income 1,000"},
        {"metric": "depreciation_amortization", "value": "250", "page": 4, "quote": "Depreciation 250"}]})
    spec = derive_ebitda([ext], "doc-1", "10k.htm")
    assert spec["value"] == "1250" and spec["source"]["document_id"] == "doc-1"
    assert spec["source"]["quote"] == "derived: Operating income 1,000 + Depreciation 250"
    assert derive_ebitda([Step("extraction", "ok", result={"created": []})], "doc-1", "10k.htm") is None


def test_crosscheck_flags_a_figure_that_differs_from_companyfacts():
    import json

    from app.flagship import Step, crosscheck_step
    ext = Step("extraction", "ok", result={"period_end": "2025-12-31", "created": [
        {"metric": "revenue", "value": "1000", "page": 1, "quote": "Revenue 1,000"},
        {"metric": "total_assets", "value": "500", "page": 2, "quote": "Total assets 500"}]})
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 999, "form": "10-K"}]}},
        "Assets": {"units": {"USD": [{"end": "2025-12-31", "val": 500, "form": "10-K"}]}}}}}
    st = crosscheck_step(ext, "1166003", lambda url: json.dumps(cf).encode())
    assert st.status == "failed" and st.result["conflicts"][0]["companyfacts"] == "999"
    assert st.result["matched"][0]["metric"] == "total_assets"
    assert crosscheck_step(ext, None, None).status == "skipped"
