from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_schedule_runs_when_due_then_waits_and_isolates_tenants():
    h = new_tenant(c, "wf1")
    other = new_tenant(c, "wf2")
    assert c.post("/workflows", headers=h, json={"name": "x", "kind": "bad", "every_days": 7}).status_code == 422
    assert c.post("/workflows", headers=h, json={"name": "x", "kind": "comps", "every_days": 0}).status_code == 422
    assert c.post("/workflows", headers=h, json={"name": "x", "kind": "comps", "every_days": 7,
                                                 "recipients": ["a\nb@x.com"]}).status_code == 422
    w = c.post("/workflows", headers=h, json={"name": "weekly", "kind": "portfolio_report", "every_days": 7,
                                              "recipients": ["lp@example.com"]}).json()
    bad = c.post("/workflows", headers=h, json={"name": "broken", "kind": "comps", "every_days": 1}).json()
    runs = {r["id"]: r["status"] for r in c.post("/workflows/run-due", headers=h).json()}
    assert runs == {w["id"]: "ok", bad["id"]: "failed"}  # missing params recorded, other schedule still ran
    assert c.post("/workflows/run-due", headers=h).json() == []  # not due again yet
    last = c.get(f"/workflows/{w['id']}/last", headers=h).json()
    assert "Breaches: 0" in last["last_result"] and last["last_status"] == "ok"
    assert c.get(f"/workflows/{w['id']}/last", headers=other).status_code == 404
    assert c.get("/workflows", headers=other).json() == []
    assert c.delete(f"/workflows/{w['id']}", headers=h).json()["active"] is False


def test_mailer_called_and_rescheduled():
    from app import workflows as wf
    from app.main import SessionLocal
    sent = []
    h = new_tenant(c, "wf3")
    w = c.post("/workflows", headers=h, json={"name": "m", "kind": "portfolio_report", "every_days": 3,
                                              "recipients": ["a@x.com", "b@x.com"]}).json()
    with SessionLocal() as db:
        row = db.get(wf.WorkflowSchedule, w["id"])
        now = datetime.now(UTC) + timedelta(hours=1)
        wf.run_due(db, row.tenant_id, None, lambda to, s, b: sent.append((to, s)), now)
        assert sent == [(["a@x.com", "b@x.com"], "[m] scheduled update")]
        assert row.next_run > (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
