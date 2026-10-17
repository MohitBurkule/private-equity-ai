"""End to end: a scheduled alert digest goes out over real SMTP and is read back through the Mailpit API.

Runs only when MAILPIT_API_URL is set (CI's api-postgres job and local runs with a Mailpit server);
SMTP_HOST and SMTP_PORT select the SMTP listener, as in production.
"""
import json
import os
import time
import urllib.request
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import workflows as wf_mod
from app.auth import principal_for_key
from app.main import SessionLocal, app
from app.models import Alert
from app.rls import bind_tenant
from tests.helpers import new_tenant

MAILPIT = os.environ.get("MAILPIT_API_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not MAILPIT or not os.environ.get("SMTP_HOST"), reason="needs Mailpit and SMTP_HOST")
c = TestClient(app)


def _mailpit(method: str, path: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(MAILPIT + path, method=method), timeout=10) as r:
        raw = r.read()
    return json.loads(raw) if method == "GET" else {}  # DELETE answers with plain text


def _wait_for_message(subject_part: str) -> dict:
    for _ in range(30):
        for m in _mailpit("GET", "/api/v1/messages").get("messages") or []:
            if subject_part in m["Subject"]:
                return m
        time.sleep(0.5)
    raise AssertionError(f"no message with subject containing {subject_part!r} reached Mailpit")


def test_alert_digest_is_sent_over_smtp_and_read_back_from_mailpit():
    _mailpit("DELETE", "/api/v1/messages")  # start from an empty inbox
    h = new_tenant(c, "mailpit-e2e")
    key = h["Authorization"].split()[1]
    with SessionLocal() as s:
        tid = principal_for_key(s, key).tenant
        bind_tenant(s, tid)
        s.add(Alert(tenant_id=tid, kind="covenant", severity="critical",
                    title="Acme: leverage breaches covenant (<= 3.0x)",
                    detail="FY2024: 4.2x against threshold 3.0x.", dedupe_key="e2e-1", fact_ids="[]",
                    status="new", created_at=datetime.now(UTC).isoformat(timespec="seconds")))
        s.commit()
    body = {"name": "IC daily", "kind": "alert_digest", "every_days": 1, "recipients": ["ic@firm.test"]}
    assert c.post("/workflows", json=body, headers=h).status_code == 201

    # The real SMTP mailer (reads SMTP_HOST/SMTP_PORT/SMTP_FROM), not a fake: this is the path production uses.
    with SessionLocal() as s:
        bind_tenant(s, tid)
        runs = wf_mod.run_due(s, tid, None, wf_mod.smtp_mailer())
    assert runs and runs[0]["status"] == "ok", runs

    msg = _wait_for_message("[IC daily] scheduled update")
    assert [t["Address"] for t in msg["To"]] == ["ic@firm.test"]
    text = _mailpit("GET", f"/api/v1/message/{msg['ID']}")["Text"]
    assert "[CRITICAL] Acme: leverage breaches covenant (<= 3.0x)" in text
    assert "FY2024: 4.2x against threshold 3.0x." in text
