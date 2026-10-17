"""Outbound webhooks: tell a tenant's own systems when a document moves between deals.

A move writes its events to an outbox table in the same transaction, so a move and its notice are kept
or lost together. A drainer posts due rows later, with backoff, and survives restarts because the outbox
is durable. A tenant webhook has no reader to check walls against, so it fails closed, twice: when the
event is queued and again when it is sent, since a deal may be flagged MNPI in between. Payloads carry
ids and deal names only, never document text, and free text goes through the tenant's PII redaction when
that flag is on.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from app import outbound
from app.acl import Principal, acl_hidden_doc_ids
from app.audit import log_event
from app.models import Deal, Document, Tenant, WebhookEndpoint, WebhookOutbox
from app.rls import bind_tenant

TIMEOUT_SECONDS = 5
MAX_ATTEMPTS = 8
BACKOFF_SECONDS = 30  # doubles per attempt: 30 s, 1 min, 2 min, ... up to about 1 h 20 min before giving up
DRAIN_BATCH = 50
SIGNATURE_HEADER = "X-PE-Signature"
RETRY_STATUS = {429, 502, 503, 504}
log = logging.getLogger("pe.webhooks")

Post = Callable[[str, bytes, dict[str, str]], int]


class UnsafeWebhookUrl(ValueError):
    pass


def check_url(url: str) -> str:
    """https only, and no literal private, loopback or link-local address, so a tenant cannot aim the
    server at its own network. Host names are resolved by the HTTP stack at send time."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host:
        raise UnsafeWebhookUrl("webhook must be an https URL")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return url
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
        raise UnsafeWebhookUrl("webhook must not point at a private or local address")
    return url


def new_secret() -> str:
    return secrets.token_hex(32)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def tenant_wide_safe(db: Session, tenant: str, doc_ids: list[str], deal_names: set[str]) -> bool:
    """True only when every document and deal in the event is open to any reader in the tenant."""
    known = {d.name: d.mnpi for d in db.query(Deal).filter(Deal.tenant_id == tenant, Deal.name.in_(deal_names)).all()}
    # A deal this session cannot see is treated as walled: fail closed rather than trust an empty lookup.
    if set(known) != deal_names or any(known.values()):
        return False
    mnpi = {d.name for d in db.query(Deal).filter_by(tenant_id=tenant, mnpi=True).all()}
    # With no identity a principal is on no access list, so every restricted document shows up here.
    restricted = acl_hidden_doc_ids(db, Principal(tenant=tenant, identity=None))
    if restricted and restricted & set(doc_ids):
        return False
    docs = db.query(Document).filter(Document.tenant_id == tenant, Document.id.in_(doc_ids)).all()
    return all(d.deal not in mnpi for d in docs)


def build_body(tenant: str, event: str, doc_ids: list[str], before: str | None, after: str | None, pii: bool) -> bytes:
    def clean(s: str | None) -> str | None:
        return outbound.text(pii, s) if s else s

    payload = {"event": event, "tenant": tenant, "document_ids": sorted(doc_ids),
               "from_deal": clean(before), "to_deal": clean(after)}
    return json.dumps(payload, sort_keys=True).encode()


def queue(db: Session, tenant: str, event: str, doc_ids: list[str], before: str | None, after: str | None,
          *, pii: bool) -> int:
    """Write one outbox row per active endpoint. Call inside the transaction that made the move, so the
    notice exists exactly when the move does. Returns the number queued; a withheld event is audited."""
    endpoints = db.query(WebhookEndpoint).filter_by(tenant_id=tenant, active=True).all()
    if not endpoints:
        return 0
    deal_names = {d for d in (before, after) if d}
    if not tenant_wide_safe(db, tenant, doc_ids, deal_names):
        log_event(db, tenant, "webhooks", "webhook.withheld", {"event": event, "document_ids": sorted(doc_ids)})
        return 0
    body = build_body(tenant, event, doc_ids, before, after, pii).decode()
    scope = json.dumps({"doc_ids": sorted(doc_ids), "deals": sorted(deal_names)})
    now = _now().isoformat()
    for e in endpoints:
        db.add(WebhookOutbox(tenant_id=tenant, endpoint_id=e.id, event=event, body=body, scope=scope,
                             status="pending", attempts=0, next_attempt_at=now, created_at=now))
    return len(endpoints)


def default_post(url: str, body: bytes, headers: dict[str, str]) -> int:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # a redirect would send the signed body somewhere unchecked
            return None

    req = urllib.request.Request(check_url(url), data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def drain(session_factory: sessionmaker, *, post: Post = default_post) -> int:
    """Send every due outbox row. Rows are tenant-scoped under RLS, so this walks tenants one by one, as
    the ingest requeue does. Returns the number of rows attempted."""
    with session_factory() as db:
        tenants = [t.id for t in db.query(Tenant).all()]
    attempted = 0
    for tid in tenants:
        with session_factory() as db:
            bind_tenant(db, tid)
            attempted += _drain_tenant(db, tid, post)
            db.commit()
    return attempted


def _drain_tenant(db: Session, tenant: str, post: Post) -> int:
    now = _now().isoformat()
    rows = (db.query(WebhookOutbox)
            .filter(WebhookOutbox.tenant_id == tenant, WebhookOutbox.status == "pending",
                    WebhookOutbox.next_attempt_at <= now)
            .order_by(WebhookOutbox.id).limit(DRAIN_BATCH)
            .with_for_update(skip_locked=True)  # two app processes must not post the same row
            .all())
    for row in rows:
        ep = db.get(WebhookEndpoint, row.endpoint_id)
        if ep is None or not ep.active:
            row.status = "cancelled"
            continue
        scope = json.loads(row.scope)
        # Re-checked at send time: a deal flagged MNPI after the move must not reach the receiver.
        if not tenant_wide_safe(db, tenant, scope["doc_ids"], set(scope["deals"])):
            row.status = "withheld"
            continue
        body = row.body.encode()
        headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(ep.secret, body)}
        ok, transient, error = _post_once(post, ep.url, body, headers)
        row.attempts += 1
        if ok:
            row.status, row.last_error = "sent", None
        elif transient and row.attempts < MAX_ATTEMPTS:
            row.next_attempt_at = (_now() + timedelta(seconds=BACKOFF_SECONDS * 2 ** (row.attempts - 1))).isoformat()
            row.last_error = error
        else:
            row.status, row.last_error = "failed", error
    return len(rows)


def _post_once(post: Post, url: str, body: bytes, headers: dict[str, str]) -> tuple[bool, bool, str]:
    """(delivered, worth retrying, reason). Only transient failures are retried; a 4xx will not change."""
    try:
        status = post(url, body, headers)
    except UnsafeWebhookUrl:
        return False, False, "unsafe url"
    except OSError as e:
        return False, True, type(e).__name__
    if status < 300:
        return True, False, ""
    return False, status in RETRY_STATUS, f"http {status}"


def start_drainer(session_factory: sessionmaker) -> threading.Thread:
    """Daemon thread that drains the outbox every WEBHOOK_DRAIN_SECONDS (default 15)."""
    interval = float(os.environ.get("WEBHOOK_DRAIN_SECONDS", "15"))

    def loop() -> None:
        while True:
            try:
                drain(session_factory)
            except Exception:
                log.exception("webhook drain failed; will retry")
            time.sleep(interval)

    t = threading.Thread(target=loop, name="webhook-drain", daemon=True)
    t.start()
    return t
