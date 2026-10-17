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
    out = c.patch(f"/dd/questions/{qid}", headers=h, json={"answer": "4%", "document_id": doc}).json()
    assert out["status"] == "answered" and out["document_id"] == doc and out["answered_at"]
    assert c.get("/dd/questions", params={"status": "open"}, headers=h).json() == []


def test_unknown_document_and_foreign_request_are_refused():
    h = new_tenant(c, "ddq2")
    qid = c.post("/dd/questions", headers=h, json={"deal": "Beta", "question": "Q?"}).json()["id"]
    bad_doc = c.patch(f"/dd/questions/{qid}", headers=h, json={"document_id": "nope"})
    assert bad_doc.status_code == 422
    bad_req = c.post("/dd/questions", headers=h, json={"deal": "Beta", "question": "Q?", "request_id": 999})
    assert bad_req.status_code == 422
