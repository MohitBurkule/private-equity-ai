from fastapi.testclient import TestClient

from app import notify
from app.main import SessionLocal, app
from tests.helpers import new_tenant
from tests.test_alerts import breach_setup

c = TestClient(app)


class FakeSMTP:
    sent: "list" = []  # noqa: RUF012

    def __init__(self, host, port, timeout=0):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_digest_sends_once_and_validates(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)  # CI sets SMTP_HOST for the Mailpit e2e test
    h, thr, o = breach_setup("nt1")
    c.post("/alerts/scan", headers=h)
    assert c.post("/alerts/digest", headers=h, json={"to": ["a@x.com"]}).status_code == 503  # no SMTP_HOST
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    assert c.post("/alerts/digest", headers=h, json={"to": ["bad address"]}).status_code == 422
    assert c.post("/alerts/digest", headers=h, json={"to": []}).status_code == 422
    FakeSMTP.sent.clear()
    assert c.post("/alerts/digest", headers=h, json={"to": ["a@x.com", "b@x.com"]}).json() == {"sent": 1}
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "a@x.com, b@x.com" and "critical" in msg["Subject"]
    assert f"[{thr}, {o}]" in msg.get_content() or str(thr) in msg.get_content()
    assert c.post("/alerts/digest", headers=h, json={"to": ["a@x.com"]}).json() == {"sent": 0}  # not repeated


def test_digest_is_per_tenant(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    a, _, _ = breach_setup("nt2")
    c.post("/alerts/scan", headers=a)
    b = new_tenant(c, "nt3")
    assert c.post("/alerts/digest", headers=b, json={"to": ["b@x.com"]}).json() == {"sent": 0}


def test_scan_all_covers_every_tenant():
    h, _, _ = breach_setup("nt4")
    res = notify.scan_all(SessionLocal)
    assert sum(res.values()) >= 1
    assert len(c.get("/alerts", headers=h).json()) == 1
    assert sum(notify.scan_all(SessionLocal).values()) == 0


def test_alert_digest_schedule_mails_new_alerts_once_and_is_unrestricted_only(monkeypatch):
    from datetime import UTC, datetime

    from app import workflows as wf_mod
    from app.auth import principal_for_key
    from app.models import Alert
    from app.rls import bind_tenant
    sent = []
    monkeypatch.setattr(wf_mod, "smtp_mailer", lambda: lambda to, subj, body: sent.append((to, subj, body)))
    h = new_tenant(c, "digest")
    key = h["Authorization"].split()[1]
    with SessionLocal() as s:
        tid = principal_for_key(s, key).tenant
        bind_tenant(s, tid)
        s.add(Alert(tenant_id=tid, kind="new_documents", severity="info", title="2 new document(s) from gmail",
                    detail="- a.pdf (https://x/1)", dedupe_key="t-1", fact_ids="[]", status="new",
                    created_at=datetime.now(UTC).isoformat(timespec="seconds")))
        s.commit()
    body = {"name": "Daily", "kind": "alert_digest", "every_days": 1, "recipients": ["ic@firm.test"]}
    assert c.post("/workflows", json=body, headers=h).status_code == 201
    assert c.post("/workflows/run-due", headers=h).status_code == 200
    assert len(sent) == 1 and sent[0][0] == ["ic@firm.test"] and "2 new document(s) from gmail" in sent[0][2]
    c.post("/workflows/run-due", headers=h)  # nothing new since the last run, so no second mail
    assert len(sent) == 1

    walled = c.post("/admin/tenants/" + tid + "/keys", json={"deals": ["atlas"]},
                    headers={"X-Admin-Token": "test-admin"}).json()["api_key"]
    r = c.post("/workflows", json=body, headers={"Authorization": f"Bearer {walled}"})
    assert r.status_code == 403
