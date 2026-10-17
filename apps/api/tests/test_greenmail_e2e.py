"""IMAP connector end to end against GreenMail, an open-source mail server (github.com/greenmail-mail-test/greenmail).
Mail goes in over real SMTP and is read back over real IMAP through the sync endpoint.

Runs only when GREENMAIL_IMAP_PORT is set, e.g. with the docker-compose `greenmail` service or the standalone jar:
  java -Dgreenmail.setup.test.imap -Dgreenmail.setup.test.smtp -Dgreenmail.hostname=127.0.0.1 \
       -Dgreenmail.port.imap=3143 -Dgreenmail.port.smtp=3025 -Dgreenmail.users=ic@firm.test:app-pass \
       -jar greenmail-standalone.jar
"""
import os
import smtplib
import uuid
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

pytestmark = pytest.mark.skipif(not os.environ.get("GREENMAIL_IMAP_PORT"), reason="GreenMail not running")

c = TestClient(app)
USER, PASSWORD = "ic@firm.test", "app-pass"


def _host() -> str:
    return os.environ.get("GREENMAIL_HOST", "127.0.0.1")


def _send(subject: str, body: str) -> None:
    e = EmailMessage()
    e["From"], e["To"], e["Subject"] = "ceo@acme.test", USER, subject
    e.set_content(body)
    with smtplib.SMTP(_host(), int(os.environ.get("GREENMAIL_SMTP_PORT", "3025")), timeout=10) as s:
        s.send_message(e)


def test_mail_sent_over_smtp_is_ingested_over_imap_with_source(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    _send(f"Acme Q3 numbers {tag}", "Revenue was 1,234 in Q3.")
    h = new_tenant(c, f"gm-{tag}")
    body = {"token": PASSWORD, "deal": None, "limit": 50, "options": {
        "host": _host(), "port": os.environ["GREENMAIL_IMAP_PORT"], "user": USER, "tls": "0"}}
    r = c.post("/connectors/imap/sync", json=body, headers=h)
    assert r.status_code == 200, r.text
    ingested = r.json()["ingested"]
    assert ingested, r.json()
    assert ingested[0]["source_url"].startswith(f"imap://{_host()}/INBOX/")
    again = c.post("/connectors/imap/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] >= 1
