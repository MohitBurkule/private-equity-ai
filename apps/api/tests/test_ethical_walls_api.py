import json

from fastapi.testclient import TestClient

from app.audit import AuditEvent
from app.main import SessionLocal, app
from app.rls import bind_tenant
from tests.helpers import new_tenant_id
from tests.test_ethical_walls import key, upload

c = TestClient(app)


def setup(name):
    admin, tid = new_tenant_id(c, name)
    assert c.post("/deals", headers=admin, json={"name": "Atlas"}).status_code == 201
    assert c.post("/deals", headers=admin, json={"name": "Atlas Inc"}).status_code == 201  # same company, warning
    assert c.post("/deals", headers=admin, json={"name": "Beta"}).status_code == 201
    upload(admin, "Atlas", f"{name} atlas")
    upload(admin, "Beta", f"{name} beta")
    walled = key(tid, role="associate", identity="alice@fund.example")
    partner = key(tid, role="partner")
    return admin, walled, partner, tid


def test_admin_sets_the_wall_and_it_is_audited_with_before_and_after():
    admin, _walled, _partner, tid = setup("api-set")
    r = c.put("/deals/Atlas/wall", json={"walled": ["Alice@Fund.example"]}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["walled"] == ["alice@fund.example"]
    assert r.json()["warnings"] == ["Atlas Inc"]  # name matching is a warning only
    c.put("/deals/Atlas/wall", json={"walled": []}, headers=admin)
    with SessionLocal() as db:
        bind_tenant(db, tid)
        events = db.query(AuditEvent).filter_by(tenant_id=tid, action="deal.wall").order_by(AuditEvent.id).all()
        assert [json.loads(e.payload) for e in events] == [
            {"deal": "Atlas", "before": [], "after": ["alice@fund.example"]},
            {"deal": "Atlas", "before": ["alice@fund.example"], "after": []}]


def test_only_an_admin_can_read_or_set_a_wall():
    _admin, _walled, partner, _tid = setup("api-roles")
    assert c.put("/deals/Atlas/wall", json={"walled": ["x"]}, headers=partner).status_code == 403
    assert c.get("/deals/Atlas/wall", headers=partner).status_code == 403


def test_a_walled_person_cannot_see_the_deal_or_its_wall():
    admin, walled, _partner, _tid = setup("api-hidden")
    c.put("/deals/Atlas/wall", json={"walled": ["alice@fund.example"]}, headers=admin)
    body = c.get("/deals", headers=walled).json()
    names = [d["name"] for d in (body["items"] if isinstance(body, dict) else body)]
    assert "Atlas" not in names and "Beta" in names
    assert c.get("/deals/Atlas/snapshot", headers=walled).status_code == 404
    assert c.get("/deals/Atlas/wall", headers=walled).status_code == 404
    assert c.put("/deals/Atlas/wall", json={"walled": []}, headers=walled).status_code == 404  # hidden, so not found


def test_a_walled_admin_cannot_see_the_wall_and_another_admin_lifts_it():
    admin, _walled, _partner, tid = setup("api-self")
    walled_admin = key(tid, role="admin", identity="root@fund.example")
    c.put("/deals/Atlas/wall", json={"walled": ["root@fund.example"]}, headers=admin)
    assert c.get("/deals/Atlas/wall", headers=walled_admin).status_code == 404  # walled, so the deal is not found
    assert c.put("/deals/Atlas/wall", json={"walled": []}, headers=walled_admin).status_code == 404
    assert c.put("/deals/Atlas/wall", json={"walled": []}, headers=admin).status_code == 200  # another admin lifts it
