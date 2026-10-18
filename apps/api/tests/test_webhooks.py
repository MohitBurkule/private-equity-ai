"""Outbound webhooks: outbox written with the move, signed posts, walls at queue and at send, retries."""
import hashlib
import hmac
import io
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import webhooks
from app.audit import AuditEvent
from app.main import SessionLocal, app
from app.models import Deal, Tenant, WebhookOutbox
from app.rls import bind_tenant
from tests.helpers import new_tenant

c = TestClient(app)


def test_urls_must_be_https_and_not_local():
    assert webhooks.check_url("https://hooks.example.com/pe") == "https://hooks.example.com/pe"
    for bad in ("http://hooks.example.com/x", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://169.254.1.1/x", "ftp://x"):
        with pytest.raises(webhooks.UnsafeWebhookUrl):
            webhooks.check_url(bad)


def test_signature_is_hmac_sha256_over_the_exact_body():
    body = b'{"event":"document.moved"}'
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert webhooks.sign("s3cret", body) == expected


def test_body_carries_ids_and_names_only_and_redacts_when_pii_is_on():
    raw = json.loads(webhooks.build_body("t1", "document.moved", ["b", "a"], "Atlas", "contact jane@example.com", pii=False))
    assert raw["document_ids"] == ["a", "b"] and raw["to_deal"] == "contact jane@example.com"
    masked = webhooks.build_body("t1", "document.moved", ["a"], None, "contact jane@example.com", pii=True)
    assert b"jane@example.com" not in masked


def _tenant_with_endpoint(name: str):
    """Headers, tenant id and signing secret for a new tenant with one endpoint registered."""
    h = new_tenant(c, name)
    r = c.post("/webhooks", headers=h, json={"url": "https://hooks.example.com/pe"})
    assert r.status_code == 201
    with SessionLocal() as db:  # the tenant table is not under RLS, so its id can be read before binding
        tid = db.query(Tenant).filter_by(name=name).one().id
    return h, tid, r.json()["secret"]


def _xlsx(label: str) -> bytes:
    wb = Workbook()
    wb.active["A1"] = label
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _queue(tid: str, doc_ids: list[str], before, after) -> int:
    with SessionLocal() as db:
        bind_tenant(db, tid)
        n = webhooks.queue(db, tid, "document.moved", doc_ids, before, after, pii=False)
        db.commit()
    return n


def _rows(tid: str) -> list[WebhookOutbox]:
    with SessionLocal() as db:
        bind_tenant(db, tid)
        return db.query(WebhookOutbox).filter_by(tenant_id=tid).order_by(WebhookOutbox.id).all()


def test_mnpi_event_is_not_queued_and_is_audited():
    h, tid, _ = _tenant_with_endpoint("hook-mnpi")
    assert c.post("/deals", headers=h, json={"name": "Secret", "mnpi": True}).status_code == 201
    assert _queue(tid, ["d1"], None, "Secret") == 0
    assert _rows(tid) == []
    with SessionLocal() as db:
        bind_tenant(db, tid)
        assert db.query(AuditEvent).filter_by(tenant_id=tid, action="webhook.withheld").count() == 1


def test_unknown_deal_name_is_not_queued():
    _, tid, _ = _tenant_with_endpoint("hook-unknown")
    assert _queue(tid, [], None, "NoSuchDeal") == 0


def test_drain_posts_a_signed_body_once_and_marks_it_sent():
    _, tid, secret = _tenant_with_endpoint("hook-open")
    assert _queue(tid, ["d9"], None, None) == 1
    got = []

    def record(url, body, headers):
        got.append((url, body, headers))
        return 200

    assert webhooks.drain(SessionLocal, post=record) >= 1
    _, body, headers = got[-1]
    assert headers[webhooks.SIGNATURE_HEADER] == webhooks.sign(secret, body)
    assert headers["Content-Type"] == "application/json"
    assert [r.status for r in _rows(tid)] == ["sent"]


def test_transient_failure_waits_then_succeeds_and_a_4xx_is_not_retried():
    _, tid, _ = _tenant_with_endpoint("hook-retry")
    _queue(tid, ["d2"], None, None)
    calls = []

    def flaky(url, body, headers):
        calls.append(url)
        return 503

    webhooks.drain(SessionLocal, post=flaky)
    row = _rows(tid)[0]
    assert row.status == "pending" and row.attempts == 1 and row.last_error == "http 503"
    assert row.next_attempt_at > datetime.now(UTC).isoformat()  # backed off, not due now
    # Pretend the backoff has passed: the next drain sends it.
    with SessionLocal() as db:
        bind_tenant(db, tid)
        db.get(WebhookOutbox, row.id).next_attempt_at = "2000-01-01T00:00:00+00:00"
        db.commit()
    webhooks.drain(SessionLocal, post=lambda u, b, hd: 204)
    assert _rows(tid)[0].status == "sent"

    _queue(tid, ["d3"], None, None)
    webhooks.drain(SessionLocal, post=lambda u, b, hd: 400)
    assert [r.status for r in _rows(tid)][-1] == "failed"


def test_walls_are_checked_again_at_send_time():
    h, tid, _ = _tenant_with_endpoint("hook-late")
    assert c.post("/deals", headers=h, json={"name": "Later"}).status_code == 201
    assert _queue(tid, ["d4"], None, "Later") == 1
    # The deal is flagged MNPI after the move was queued.
    with SessionLocal() as db:
        bind_tenant(db, tid)
        db.query(Deal).filter_by(tenant_id=tid, name="Later").update({"mnpi": True})
        db.commit()
    sent = []
    webhooks.drain(SessionLocal, post=lambda u, b, hd: sent.append(u) or 204)
    assert sent == []
    assert [r.status for r in _rows(tid)] == ["withheld"]


def test_bulk_move_writes_the_outbox_in_its_own_transaction():
    h, tid, _ = _tenant_with_endpoint("hook-bulk")
    assert c.post("/deals", headers=h, json={"name": "Alpha"}).status_code == 201
    assert c.post("/deals", headers=h, json={"name": "Beta"}).status_code == 201
    a = c.post("/documents", headers=h, data={"deal": "Alpha"},
               files={"file": ("a.xlsx", _xlsx("alpha-one"), "x")}).json()["id"]
    r = c.post("/documents/bulk-deal", headers=h, json={"doc_ids": [a], "deal": "Beta"})
    assert r.status_code == 200 and r.json()["moved"] == [a]
    rows = _rows(tid)
    assert len(rows) == 1 and json.loads(rows[0].body)["document_ids"] == [a]


def test_endpoint_api_rejects_http_and_lists_without_secrets():
    h = new_tenant(c, "hook-api")
    assert c.post("/webhooks", headers=h, json={"url": "http://x.example.com"}).status_code == 422
    r = c.post("/webhooks", headers=h, json={"url": "https://hooks.example.com/pe"})
    assert r.status_code == 201 and len(r.json()["secret"]) == 64
    listed = c.get("/webhooks", headers=h).json()
    assert listed and "secret" not in listed[0]
    assert c.delete(f"/webhooks/{r.json()['id']}", headers=h).status_code == 204
    assert c.get("/webhooks", headers=h).json() == []
