"""Alert digest → Slack and Teams, through the real endpoint: an alert is seeded, an alert_digest schedule runs
via POST /workflows/run-due, and each configured webhook gets the digest text once. Webhook HTTP is a recorder;
the wiremock variant of the posts is in tests/test_wiremock_adapters.py."""
from datetime import UTC, datetime

from fastapi.testclient import TestClient

import app.main as m
from app import chat_alerts
from app.auth import principal_for_key
from app.main import SessionLocal, app
from app.models import Alert
from app.rls import bind_tenant
from tests.helpers import new_tenant

c = TestClient(app)
SLACK = "https://hooks.slack.com/services/T1/B1/xyz"
TEAMS = "https://outlook.office.com/webhookb2/abc/IncomingWebhook"


def test_digest_is_posted_to_slack_and_teams_once(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", SLACK)
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", TEAMS)
    posted = []

    def recorder(url, headers):
        posted.append((url, headers["X-Post-Body"]))
        return b""

    monkeypatch.setattr(m, "chat_poster", lambda pii=False: chat_alerts.chat_poster(http=recorder, pii=pii))
    h = new_tenant(c, "chat-e2e")
    tid = principal_for_key(SessionLocal(), h["Authorization"].split()[1]).tenant
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(Alert(tenant_id=tid, kind="new_documents", severity="info", title="3 new document(s) from sharepoint",
                    detail="- cim.pdf", dedupe_key="chat-1", fact_ids="[]", status="new",
                    created_at=datetime.now(UTC).isoformat(timespec="seconds")))
        s.commit()
    body = {"name": "Team digest", "kind": "alert_digest", "every_days": 1, "recipients": []}
    assert c.post("/workflows", json=body, headers=h).status_code == 201
    assert c.post("/workflows/run-due", headers=h).status_code == 200

    assert [u for u, _ in posted] == [SLACK, TEAMS]
    assert all("[Team digest]" in b and "3 new document(s) from sharepoint" in b for _, b in posted)
    c.post("/workflows/run-due", headers=h)  # nothing new since the last run, so nothing posted again
    assert len(posted) == 2
