import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_question_log_open_then_answered_with_visible_source():
    h = new_tenant(c, "ddq1")
    r = c.post("/dd/questions", headers=h, json={"deal": "Acme", "question": "What is FY24 churn?"})
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    assert c.get("/dd/questions", params={"deal": "Acme", "status": "open"}, headers=h).json()[0]["id"] == qid

    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "churn", 4
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("mgmt.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    quote = "Sheet!B1: 4 | row: churn"
    bare = c.patch(f"/dd/questions/{qid}", headers=h, json={"answer": "4%", "document_id": doc})
    assert bare.status_code == 422
    wrong = c.patch(f"/dd/questions/{qid}", headers=h,
                    json={"answer": "4%", "document_id": doc, "page": 1, "quote": "Sheet!B1: 9 | row: churn"})
    assert wrong.status_code == 422 and "quote not found" in wrong.text
    out = c.patch(f"/dd/questions/{qid}", headers=h,
                  json={"answer": "4%", "document_id": doc, "page": 1, "quote": quote}).json()
    assert out["status"] == "answered" and out["document_id"] == doc and out["answered_at"]
    assert out["page"] == 1 and out["quote"] == quote
    assert c.get("/dd/questions", params={"status": "open"}, headers=h).json() == []


def test_unknown_document_and_foreign_request_are_refused():
    h = new_tenant(c, "ddq2")
    qid = c.post("/dd/questions", headers=h, json={"deal": "Beta", "question": "Q?"}).json()["id"]
    bad_doc = c.patch(f"/dd/questions/{qid}", headers=h,
                      json={"answer": "x", "document_id": "nope", "page": 1, "quote": "x"})
    assert bad_doc.status_code == 422
    bad_req = c.post("/dd/questions", headers=h, json={"deal": "Beta", "question": "Q?", "request_id": 999})
    assert bad_req.status_code == 422
