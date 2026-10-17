"""Mailpit, the fake SMTP server used in dev (see docker-compose.yml). Mailpit has no IMAP, so ingest reads
its HTTP API instead: the stored-message list, then each raw RFC822 message. Each message is ingested
through the normal email path, and its citation points at the message's page in the Mailpit UI.
Only localhost is allowed, because this is a dev inbox, never a mail host a firm should reach from here."""
from __future__ import annotations

import hashlib
import urllib.request
from urllib.parse import urlparse

from app.connectors.base import Connector, ConnectorError, Item, default_http

LOCAL_HOSTS = {"localhost", "127.0.0.1", "mailpit"}  # 'mailpit' is the compose service name


def _local_http(url: str, headers: dict[str, str]) -> bytes:
    """Plain http, only to LOCAL_HOSTS: the connector guard in default_http is https-only."""
    if (urlparse(url).hostname or "") not in LOCAL_HOSTS:
        raise ValueError("mailpit connector only calls local hosts")
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


class Mailpit(Connector):
    """opts: base=<Mailpit URL> (default http://localhost:8025). No token is needed; pass any non-empty value."""
    name, label = "mailpit", "Mailpit (dev inbox)"

    def __init__(self, token: str, http=default_http, **opts: str):
        super().__init__(token, http, **opts)
        if http is default_http:
            self.http = _local_http

    def _base(self) -> str:
        base = self.opts.get("base", "http://localhost:8025").rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
            raise ConnectorError("mailpit base must be a local http(s) URL")
        return base

    def items(self, limit: int = 50):
        base = self._base()
        listing = self._get_json(f"{base}/api/v1/messages?limit={min(max(limit, 1), 100)}")
        for m in listing.get("messages", [])[:limit]:
            mid = m["ID"]
            raw = self.http(f"{base}/api/v1/message/{mid}/raw", {"Accept": "message/rfc822"})
            yield Item(f"mailpit:{mid}", f"mailpit-{mid}.eml", raw, f"{base}/view/{mid}",
                       hashlib.sha256(raw).hexdigest()[:16])
