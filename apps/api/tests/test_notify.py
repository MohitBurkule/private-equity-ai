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
