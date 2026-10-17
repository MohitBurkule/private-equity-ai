from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_access_report_lists_logged_actions_on_one_deal():
    h = new_tenant(c, "access-report")
    c.post("/deals", headers=h, json={"name": "Watched"})
    c.post("/deals", headers=h, json={"name": "Other"})
    c.patch("/deals/Watched", headers=h, json={"note": "first"})
    r = c.get("/compliance/access-report", params={"deal": "Watched"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {e["action"] for e in body["events"]} >= {"deal.create", "deal.update"}
    assert all(e["payload"].get("name") == "Watched" for e in body["events"])
    assert sum(body["by_actor"].values()) == len(body["events"])
    assert "Document reads" in body["note"]


def test_access_report_needs_unrestricted_govern_role():
    t = c.post("/admin/tenants", json={"name": "access-report2"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=admin, json={"name": "Sealed"})
    viewer = c.post(f"/admin/tenants/{t['tenant_id']}/keys", json={"role": "analyst"},
                    headers={"X-Admin-Token": "test-admin"}).json()
    assert c.get("/compliance/access-report", params={"deal": "Sealed"},
                 headers={"Authorization": f"Bearer {viewer['api_key']}"}).status_code == 403
