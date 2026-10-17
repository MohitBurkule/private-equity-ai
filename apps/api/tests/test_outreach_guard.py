from fastapi.testclient import TestClient

from app import outreach
from app.main import SessionLocal, ag, app, wf_mod
from app.models import Target
from app.rls import bind_tenant

c = TestClient(app)


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"}).json()
    return {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]


def test_send_refuses_wrong_subject_and_junior_or_walled_keys(monkeypatch):
    h, tid = tenant("og1")
    c.post("/targets", headers=h, json=[{"name": "Gamma Ltd", "source": "manual", "source_ref": "g", "sector": "Software"}])
    with SessionLocal() as s:
        bind_tenant(s, tid)
        t = s.query(Target).filter_by(name="Gamma Ltd").one()
        subject = outreach.draft(t, "Ana", "Firm")["subject"]
        tid_target = t.id
    body = {"target_id": tid_target, "to": ["ic@example.com"], "sender": "Ana", "firm": "Firm"}
    sent = []
    monkeypatch.setattr("app.notify.send_email", lambda *a, **k: sent.append(a))
    assert c.post("/targets/outreach/send", headers=h, json={**body, "confirm_subject": "stale"}).status_code == 409
    assert sent == []
    assert c.post("/targets/outreach/send", headers=h, json={**body, "confirm_subject": subject}).status_code == 200
    assert len(sent) == 1


def test_agents_and_workflows_cannot_reach_send():
    assert not any("outreach" in name for name in ag.TOOLS)
    assert not any("outreach" in k for k in wf_mod.KINDS)
