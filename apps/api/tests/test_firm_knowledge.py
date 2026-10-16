import io
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app, llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)


class Fake:
    def __init__(self, values):
        self.values = values

    def complete(self, system, prompt):
        return json.dumps({"values": self.values})


def upload(h, rows):
    wb = Workbook()
    for i, t in enumerate(rows, 1):
        wb.active.cell(i, 1, t)
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("policy.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def page_text(h, doc):
    return c.get(f"/documents/{doc}/pages/1", headers=h).json()["text"]


def run(h, doc, values):
    app.dependency_overrides[llm_dependency] = lambda: Fake(values)
    try:
        return c.post("/firm-knowledge/extract", headers=h, json={"document_id": doc})
    finally:
        app.dependency_overrides.pop(llm_dependency)


def test_extract_verify_review_profile():
    h = new_tenant(c, "fk1")
    doc = upload(h, ["Board meets quarterly", "Deals above 50 million need managing partner sign-off"])
    assert "Board meets quarterly" in page_text(h, doc)
    r = run(h, doc, [
        {"key": "board_meeting_frequency", "value": "quarterly", "page": 1, "quote": "Board meets quarterly"},
        {"key": "partner_signoff_threshold", "value": "50 million", "page": 1,
         "quote": "Deals above 50 million need managing partner sign-off"},
        {"key": "partner_signoff_threshold", "value": "75 million", "page": 1, "quote": "Board meets quarterly"},
        {"key": "hold_period", "value": "5 years", "page": 1, "quote": "not on the page"},
        {"key": "bogus", "value": "x", "page": 1, "quote": "Board meets quarterly"},
    ]).json()
    assert len(r["saved"]) == 2
    assert sorted(x["reason"] for x in r["rejected"]) == [
        "quote not found on cited page", "unknown key", "value contains a number that is not in the quote"]
    assert c.get("/firm-knowledge", headers=h).json()["profile"] == {}  # pending is hidden
    fid = r["saved"][0]["id"]
    assert c.post(f"/firm-knowledge/{fid}/review", headers=h, json={"status": "accepted"}).status_code == 200
    p = c.get("/firm-knowledge", headers=h).json()
    assert p["profile"]["board_meeting_frequency"][0]["source"]["quote"] == "Board meets quarterly"
    assert p["coverage"]["known"] == 1
    assert c.post(f"/firm-knowledge/{fid}/review", headers=h, json={"status": "accepted", "value": "every 9 months"}).status_code == 422
    assert c.post(f"/firm-knowledge/{fid}/review", headers=h, json={"status": "bad"}).status_code == 422
    assert run(h, doc, [{"key": "board_meeting_frequency", "value": "quarterly", "page": 1,
                         "quote": "Board meets quarterly"}]).json()["saved"] == []  # no duplicate


def test_isolation_and_terms():
    a, b = new_tenant(c, "fk2"), new_tenant(c, "fk3")
    doc = upload(a, ["Board meets quarterly"])
    assert run(b, doc, []).status_code == 404
    r = run(a, doc, [{"key": "board_meeting_frequency", "value": "quarterly", "page": 1, "quote": "Board meets quarterly"}]).json()
    assert c.post(f"/firm-knowledge/{r['saved'][0]['id']}/review", headers=b, json={"status": "accepted"}).status_code == 404
    terms = c.get("/firm-knowledge/terms", headers=a).json()
    assert len(terms) >= 40 and {"capiq_usage", "lp_reporting_tone"} <= {t["key"] for t in terms}
