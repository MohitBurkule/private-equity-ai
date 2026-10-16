from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_covenants import ADMIN, setup

c = TestClient(app)


def breach_setup(name):
    h = new_tenant(c, name)
    co, fact = setup(h)
    thr = fact("debt.max_net_leverage_x", "cov", 0)
    o = fact("net_leverage_x", "Q2", 2)
    c.post(f"/portfolio/companies/{co}/observations", params={"fact_id": o}, headers=h)
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "net_leverage_x", "operator": "<=",
                                                         "threshold_fact_id": thr}, headers=h)
    return h, thr, o


def test_scan_creates_cited_alert_once_and_status_flow():
    h, thr, o = breach_setup("al1")
    made = c.post("/alerts/scan", headers=h).json()["created"]
    assert len(made) == 1 and made[0]["severity"] == "critical" and set(made[0]["fact_ids"]) == {thr, o}
    assert "Co" in made[0]["title"]
    assert c.post("/alerts/scan", headers=h).json()["created"] == []  # idempotent
    aid = made[0]["id"]
    assert c.post(f"/alerts/{aid}/status", headers=h, json={"status": "read"}).json()["status"] == "read"
    assert c.get("/alerts", headers=h, params={"status": "new"}).json() == []
    assert c.post(f"/alerts/{aid}/status", headers=h, json={"status": "bogus"}).status_code == 422


def test_isolation_and_restricted_key_blocked():
    h, _, _ = breach_setup("al2")
    c.post("/alerts/scan", headers=h)
    other = new_tenant(c, "al3")
    assert c.get("/alerts", headers=other).json() == []
    assert c.post("/alerts/1/status", headers=other, json={"status": "read"}).status_code == 404
    tid = c.post("/admin/tenants", json={"name": "al4"}, headers=ADMIN).json()["tenant_id"]
    k = c.post(f"/admin/tenants/{tid}/keys", json={"deals": ["alpha"]}, headers=ADMIN).json()["api_key"]
    r = c.get("/alerts", headers={"Authorization": f"Bearer {k}"})
    assert r.status_code == 403
