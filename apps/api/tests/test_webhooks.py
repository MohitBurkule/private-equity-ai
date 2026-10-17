"""Outbound webhooks: signed posts, fail-closed walls, PII redaction, and the endpoint API."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import webhooks
from app.main import SessionLocal, app
from app.models import WebhookEndpoint
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


def test_retry_once_on_transient_failure_then_stop():
    calls = []

    def flaky(url, body, headers):
        calls.append(url)
        return 503 if len(calls) == 1 else 204

    assert webhooks._send(flaky, "https://hooks.example.com/x", b"{}", {}) == "sent"
    assert len(calls) == 2

    def refused(url, body, headers):
        calls.append(url)
        return 400

    calls.clear()
    assert webhooks._send(refused, "https://hooks.example.com/x", b"{}", {}) == "http 400"
    assert len(calls) == 1


def test_event_touching_an_mnpi_deal_is_withheld_from_every_endpoint():
    h, tid, _ = _tenant_with_endpoint("hook-mnpi")
    assert c.post("/deals", headers=h, json={"name": "Secret", "mnpi": True}).status_code == 201
    sent = []
    with SessionLocal() as db:
        bind_tenant(db, tid)
        out = webhooks.emit(db, tid, "document.moved", ["d1"], None, "Secret", pii=False,
                            post=lambda u, b, hd: sent.append(u) or 204)
    assert sent == []
    assert set(out.values()) == {"withheld"}


def test_unknown_deal_name_is_withheld():
    _, tid, _ = _tenant_with_endpoint("hook-unknown")
    sent = []
    with SessionLocal() as db:
        bind_tenant(db, tid)
        out = webhooks.emit(db, tid, "document.moved", [], None, "NoSuchDeal", pii=False,
                            post=lambda u, b, hd: sent.append(u) or 204)
    assert sent == [] and set(out.values()) == {"withheld"}


def test_event_on_open_deals_is_signed_and_delivered():
    h, tid, secret = _tenant_with_endpoint("hook-open")
    assert c.post("/deals", headers=h, json={"name": "Open"}).status_code == 201
    got = {}

    def record(url, body, headers):
        got.update(body=body, headers=headers)
        return 200

    with SessionLocal() as db:
        bind_tenant(db, tid)
        out = webhooks.emit(db, tid, "document.moved", ["d9"], None, "Open", pii=False, post=record)
    assert list(out.values()) == ["sent"]
    assert got["headers"][webhooks.SIGNATURE_HEADER] == webhooks.sign(secret, got["body"])
    assert got["headers"]["Content-Type"] == "application/json"


def test_endpoint_api_rejects_http_and_lists_without_secrets():
    h = new_tenant(c, "hook-api")
    assert c.post("/webhooks", headers=h, json={"url": "http://x.example.com"}).status_code == 422
    r = c.post("/webhooks", headers=h, json={"url": "https://hooks.example.com/pe"})
    assert r.status_code == 201 and len(r.json()["secret"]) == 64
    listed = c.get("/webhooks", headers=h).json()
    assert listed and "secret" not in listed[0]
    assert c.delete(f"/webhooks/{r.json()['id']}", headers=h).status_code == 204
    assert c.get("/webhooks", headers=h).json() == []


def _tenant_with_endpoint(name: str):
    """Headers for a new tenant with one endpoint registered, and the tenant id and secret the endpoint holds."""
    h = new_tenant(c, name)
    r = c.post("/webhooks", headers=h, json={"url": "https://hooks.example.com/pe"})
    assert r.status_code == 201
    with SessionLocal() as db:
        tid = db.get(WebhookEndpoint, r.json()["id"]).tenant_id
    return h, tid, r.json()["secret"]


def test_background_delivery_applies_the_same_walls():
    _, tid, _ = _tenant_with_endpoint("hook-bg")
    sent = []
    fut = webhooks.enqueue(SessionLocal, tid, "document.moved", ["d1"], None, "NoSuchDeal", pii=False,
                           post=lambda u, b, hd: sent.append(u) or 204)
    assert set(fut.result(timeout=10).values()) == {"withheld"}
    assert sent == []
