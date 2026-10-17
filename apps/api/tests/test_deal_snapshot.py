from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_snapshot_reports_ic_state_and_counts():
    h = new_tenant(c, "snapshot")
    assert c.post("/deals", headers=h, json={"name": "Snap Deal"}).status_code in (200, 201)
    decision = {"deal": "Snap Deal", "outcome": "hold", "rationale": "wait", "dissent": "too rich", "dissenter": "VP"}
    c.post("/ic/decisions", headers=h, json=decision)
    r = c.get("/deals/Snap Deal/snapshot", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deal"] == "Snap Deal"
    assert body["ic"]["recorded"] is True
    assert body["ic"]["latest"]["outcome"] == "hold"
    assert body["ic"]["dissents"] == 1
    assert body["ic"]["changed_since_ic"] == 0
    assert body["documents"]["count"] == 0
    assert body["dd"] == {"total": 0, "closed": 0, "pct_complete": None}
    assert body["open_alerts"] == 0


def test_snapshot_without_ic_or_deal():
    h = new_tenant(c, "snapshot2")
    assert c.post("/deals", headers=h, json={"name": "Quiet Deal"}).status_code in (200, 201)
    body = c.get("/deals/Quiet Deal/snapshot", headers=h).json()
    assert body["ic"]["recorded"] is False
    assert body["ic"]["latest"] is None
    assert body["ic"]["dissents"] == 0
    assert c.get("/deals/Nope/snapshot", headers=h).status_code == 404
