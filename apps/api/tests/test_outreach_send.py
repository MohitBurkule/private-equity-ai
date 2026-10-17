from fastapi.testclient import TestClient

from app import notify
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_outreach_send_attaches_research_docx_and_checks_tenant(monkeypatch):
    h, other = new_tenant(c, "os1"), new_tenant(c, "os2")
    c.post("/targets", headers=h, json=[{"name": "Acme", "source_ref": "a", "sector": "Software",
                                         "revenue": "150000000", "currency": "USD", "revenue_period": "FY2023",
                                         "revenue_url": "http://sec/x"}])
    tid = c.get("/targets", headers=h).json()["items"][0]["id"]
    sent = {}
    monkeypatch.setattr(notify, "send_email", lambda to, subject, body, attachment=None: sent.update(
        to=to, subject=subject, attachment=attachment))
    body = {"target_id": tid, "to": ["ceo@example.com"], "sender": "Sam", "firm": "Fund I"}
    r = c.post("/targets/outreach/send", headers=h, json=body)
    assert r.status_code == 200 and r.json() == {"sent": 1, "attached": f"research-{tid}.docx"}
    filename, data, mime = sent["attachment"]
    assert filename == f"research-{tid}.docx" and data[:2] == b"PK"  # a real .docx is a zip
    assert mime.endswith("wordprocessingml.document")
    assert sent["to"] == ["ceo@example.com"] and sent["subject"] == "Introduction from Fund I"
    assert c.post("/targets/outreach/send", headers=other, json=body).status_code == 404
    assert c.post("/targets/outreach/send", headers=h, json={**body, "to": ["not-an-address"]}).status_code == 422
