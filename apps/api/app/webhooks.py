"""Outbound webhooks: tell a tenant's own systems when a document moves between deals.

Each event is one HMAC-signed JSON POST per endpoint. A tenant webhook has no reader to check walls
against, so it fails closed: if the event touches an MNPI deal, a document under a source access list,
or a deal that is itself walled, nothing is sent. Payloads carry ids and deal names only, never document
text, and free text goes through the tenant's PII redaction when that flag is on.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from urllib.parse import urlparse

from sqlalchemy.orm import Session, sessionmaker

from app import outbound
from app.acl import Principal, acl_hidden_doc_ids
from app.models import Deal, Document, WebhookEndpoint
from app.rls import bind_tenant

TIMEOUT_SECONDS = 5
log = logging.getLogger("pe.webhooks")
# Sends run off the request thread so a slow receiver never holds up a bulk move. The queue is in-process:
# an event queued when the server stops is lost, which is the trade-off for not adding a broker.
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("WEBHOOK_WORKERS", "2")), thread_name_prefix="webhook")
SIGNATURE_HEADER = "X-PE-Signature"
RETRY_STATUS = {429, 502, 503, 504}

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


def emit(db: Session, tenant: str, event: str, doc_ids: list[str], before: str | None, after: str | None,
         *, pii: bool, post: Post = default_post) -> dict[str, str]:
    """Send one event to every active endpoint of the tenant. Returns the outcome per endpoint id."""
    endpoints = db.query(WebhookEndpoint).filter_by(tenant_id=tenant, active=True).all()
    if not endpoints:
        return {}
    deal_names = {d for d in (before, after) if d}
    if not tenant_wide_safe(db, tenant, doc_ids, deal_names):
        return {str(e.id): "withheld" for e in endpoints}
    body = build_body(tenant, event, doc_ids, before, after, pii)
    outcome: dict[str, str] = {}
    for e in endpoints:
        headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(e.secret, body)}
        outcome[str(e.id)] = _send(post, e.url, body, headers)
    return outcome


def _send(post: Post, url: str, body: bytes, headers: dict[str, str]) -> str:
    # One retry, and only on transient failures. A write may have landed, so no more than that.
    for attempt in range(2):
        try:
            status = post(url, body, headers)
        except UnsafeWebhookUrl:
            return "unsafe url"
        except OSError:
            if attempt == 0:
                continue
            return "failed"
        if status < 300:
            return "sent"
        if status not in RETRY_STATUS or attempt == 1:
            return f"http {status}"
    return "failed"


def enqueue(session_factory: sessionmaker, tenant: str, event: str, doc_ids: list[str], before: str | None,
            after: str | None, *, pii: bool, post: Post = default_post) -> Future:
    """Send in the background. The walls are checked there, in a fresh session bound to the tenant, so they
    see the same data a request would, not whatever the request session had loaded."""
    return _pool.submit(_deliver, session_factory, tenant, event, doc_ids, before, after, pii, post)


def _deliver(session_factory: sessionmaker, tenant: str, event: str, doc_ids: list[str], before: str | None,
             after: str | None, pii: bool, post: Post) -> dict[str, str]:
    with session_factory() as db:
        bind_tenant(db, tenant)
        try:
            return emit(db, tenant, event, doc_ids, before, after, pii=pii, post=post)
        except Exception:
            log.exception("webhook delivery failed for tenant %s", tenant)
            return {"error": "delivery failed"}
