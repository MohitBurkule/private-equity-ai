import os

from fastapi.testclient import TestClient

from app import workflows as wf_mod
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_schedule_runs_when_due_then_waits_and_isolates_tenants(monkeypatch):
    if not os.environ.get("MAILPIT_API_URL"):  # no mail server here: keep results in the outbox, not SMTP
        monkeypatch.setattr(wf_mod, "smtp_mailer", lambda: None)
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


def test_mailer_called_and_rescheduled(monkeypatch):
    from app import workflows as wf
    sent = []
    monkeypatch.setattr(wf, "smtp_mailer", lambda: lambda to, s, b: sent.append((to, s)))
    h = new_tenant(c, "wf3")
    w = c.post("/workflows", headers=h, json={"name": "m", "kind": "portfolio_report", "every_days": 3,
                                              "recipients": ["a@x.com", "b@x.com"]}).json()
    c.post("/workflows/run-due", headers=h)
    assert sent == [(["a@x.com", "b@x.com"], "[m] scheduled update")]
    after = c.get("/workflows", headers=h).json()[0]
    assert after["next_run"] > w["next_run"] and after["last_status"] == "ok"
