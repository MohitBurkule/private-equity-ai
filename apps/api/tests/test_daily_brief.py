from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import workflows as wf
from app.alerts import brief_text
from app.main import SessionLocal, app
from app.models import Alert
from app.rls import bind_tenant

c = TestClient(app)


def test_daily_brief_mails_new_alerts_once_and_stays_quiet_when_empty():
    t = c.post("/admin/tenants", json={"name": "db1"}, headers={"X-Admin-Token": "test-admin"}).json()
    h, tid = {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]
    r = c.post("/workflows", headers=h, json={"name": "Daily", "kind": "daily_brief", "every_days": 1,
                                               "recipients": ["ic@example.com"]})
    assert r.status_code == 201, r.text
    now = datetime.now(UTC)
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(Alert(tenant_id=tid, kind="covenant", severity="critical", title="Breach: Acme", detail="ND/EBITDA 5.1x",
                    dedupe_key="db-k1", fact_ids="[7]", status="new", created_at=now.isoformat(timespec="seconds")))
        s.commit()
    sent = []
    with SessionLocal() as s:
        bind_tenant(s, tid)
        wf.run_due(s, tid, None, mailer=lambda to, subj, body: sent.append((to, body)),
                   now=now + timedelta(seconds=1))
    assert len(sent) == 1 and sent[0][0] == ["ic@example.com"]
    assert "1 alert(s) since" in sent[0][1] and "[CRITICAL] Breach: Acme" in sent[0][1] and "fact ids [7]" in sent[0][1]
    with SessionLocal() as s:
        bind_tenant(s, tid)
        wf.run_due(s, tid, None, mailer=lambda to, subj, body: sent.append((to, body)),
                   now=now + timedelta(days=2))
    assert len(sent) == 1  # nothing new since the last run, so no mail


def test_brief_text_empty():
    assert brief_text({"since": "2026-10-16T00:00:00+00:00", "total": 0, "by_severity": {}, "top": []}).startswith("No alerts since")
