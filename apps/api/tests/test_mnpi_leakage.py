from fastapi.testclient import TestClient

from app import agent as ag
from app.acl import Principal
from app.audit import AuditEvent
from app.main import SessionLocal, app
from app.models import Deal

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def _setup(name):
    t = c.post("/admin/tenants", json={"name": name}, headers=ADMIN).json()
    tid = t["tenant_id"]
    creator = {"Authorization": f"Bearer {t['api_key']}"}
    outsider_key = c.post(f"/admin/tenants/{tid}/keys", json={"role": "partner"}, headers=ADMIN).json()["api_key"]
    outsider = {"Authorization": f"Bearer {outsider_key}"}
    assert c.post("/deals", headers=creator, json={"name": "Secret", "mnpi": True}).status_code == 201
    assert c.post("/deals", headers=creator, json={"name": "Open Deal"}).status_code == 201
    c.post("/targets", headers=creator, json=[
        {"name": "Secret", "source": "manual", "source_ref": "s", "sector": "Software"},
        {"name": "Plain Co", "source": "manual", "source_ref": "p", "sector": "Software"}])
    items = c.get("/targets", headers=creator).json()["items"]
    ids = {t_["name"]: t_["id"] for t_ in items}
    return tid, creator, outsider, ids


def test_seen_before_does_not_name_an_mnpi_deal_to_someone_outside_it():
    _, creator, outsider, _ = _setup("leak-seen")
    out = c.get("/seen-before?q=Secret", headers=outsider).json()
    assert all(h["kind"] != "deal" for h in out["hits"])
    inside = c.get("/seen-before?q=Secret", headers=creator).json()
    assert any(h["kind"] == "deal" for h in inside["hits"])


def test_outreach_draft_and_queue_refuse_a_target_that_matches_an_mnpi_deal():
    _, creator, outsider, ids = _setup("leak-outreach")
    body = {"target_ids": [ids["Secret"]], "sender": "Ana", "firm": "Firm"}
    assert c.post("/targets/outreach", headers=outsider, json=body).status_code == 409
    assert c.post("/targets/outreach/queue", headers=outsider, json=body).status_code == 409
    assert c.post("/targets/outreach", headers=creator, json=body).status_code == 200  # the creator may see it
    ok = {"target_ids": [ids["Plain Co"]], "sender": "Ana", "firm": "Firm"}
    assert c.post("/targets/outreach", headers=outsider, json=ok).status_code == 200


def test_agent_deal_list_leaves_out_mnpi_deals_for_someone_outside_them():
    tid, _, _, _ = _setup("leak-agent")
    db = SessionLocal()
    try:
        who = Principal(tenant=tid, role="partner", key_id="someone-else")
        names = [d["name"] for d in ag.TOOLS["list_deals"].fn(ag.Ctx(db, who))]
        assert "Open Deal" in names and "Secret" not in names
        cleared = Principal(tenant=tid, role="partner", key_id="x", deals=frozenset({"Secret", "Open Deal"}))
        assert "Secret" in [d["name"] for d in ag.TOOLS["list_deals"].fn(ag.Ctx(db, cleared))]  # named in its scope
        walled = Principal(tenant=tid, role="partner", key_id="x", deals=frozenset({"Open Deal"}))
        assert "Secret" not in [d["name"] for d in ag.TOOLS["list_deals"].fn(ag.Ctx(db, walled))]
        assert db.query(Deal).filter_by(tenant_id=tid, name="Secret").one().mnpi is True
    finally:
        db.close()


def test_seen_before_audits_when_a_cleared_person_sees_an_mnpi_deal():
    tid, creator, _, _ = _setup("leak-audit")
    assert c.get("/seen-before?q=Secret", headers=creator).status_code == 200
    db = SessionLocal()
    try:
        actions = [e.action for e in db.query(AuditEvent).filter_by(tenant_id=tid).all()]
    finally:
        db.close()
    assert "mnpi.view" in actions
