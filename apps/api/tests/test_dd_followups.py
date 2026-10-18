"""Follow-up drafts come only from open lines: an open request or an unanswered question. Nothing is sent."""
from fastapi.testclient import TestClient

from app.dd_followups import drafts
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_drafts_keep_order_and_kind():
    out = drafts(["Audited FY23 accounts"], ["Why did EBITDA fall in Q2?"])
    assert out == [{"kind": "request", "text": "Please provide Audited FY23 accounts."},
                   {"kind": "chaser", "text": "Following up on our earlier question: Why did EBITDA fall in Q2?"}]


def test_no_open_lines_no_drafts():
    assert drafts([], []) == []


def test_endpoint_drafts_only_open_items_and_waived_lines_drop_out():
    h = new_tenant(c, "fu1")
    open_r = c.post("/dd/requests", headers=h, json={"deal": "Acme", "category": "Financial", "title": "QoE report"})
    waived = c.post("/dd/requests", headers=h, json={"deal": "Acme", "category": "Legal", "title": "Lease schedule"})
    assert open_r.status_code == 201 and waived.status_code == 201
    c.patch(f"/dd/requests/{waived.json()['id']}", headers=h, json={"status": "waived"})
    c.post("/dd/questions", headers=h, json={"deal": "Acme", "question": "What drove the Q2 margin dip?"})
    out = c.get("/dd/followups", headers=h, params={"deal": "Acme"}).json()
    assert [d["text"] for d in out] == ["Please provide QoE report.",
                                        "Following up on our earlier question: What drove the Q2 margin dip?"]
