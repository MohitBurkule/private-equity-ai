"""Connector contract. A connector only lists and downloads; ingestion, deal walls and citation
records are handled once, in `sync`, so no connector can bypass them.

HTTP is injectable (`Http`) so tests and offline demos replay recorded responses.
Credentials are passed per call and never stored by this layer.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import ClassVar

Http = Callable[[str, dict[str, str]], bytes]


RETRY_STATUS = {429, 502, 503, 504}  # 429 is always retried; 5xx only for reads, since a write may have landed
MAX_ATTEMPTS = 4
MAX_WAIT_S = 30.0


def _wait(err: urllib.error.HTTPError, attempt: int) -> float:
    """Retry-After in seconds when the server sends one, else 1, 2, 4 seconds. Capped at MAX_WAIT_S."""
    try:
        return min(float(err.headers.get("Retry-After", "")), MAX_WAIT_S)
    except (TypeError, ValueError):
        return min(2.0 ** (attempt - 1), MAX_WAIT_S)


def default_http(url: str, headers: dict[str, str]) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("connectors only call https URLs")
    headers = dict(headers)
    body = headers.pop("X-Post-Body", None)  # POST-only APIs (Dropbox): see connectors/files.py
    method = headers.pop("X-Method", None)  # PATCH/PUT writes (CRM stage sync): see connectors/crm.py
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, headers=headers, method=method,
                                     data=body.encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            is_read = body is None and method in (None, "GET")
            retry = e.code == 429 or (e.code in RETRY_STATUS and is_read)
            if not retry or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(_wait(e, attempt))
    raise AssertionError("unreachable")


class ConnectorError(Exception):
    pass


@dataclass(frozen=True)
class Item:
    external_id: str  # stable id in the source system
    name: str  # filename used for ingestion (keeps extension)
    data: bytes
    url: str  # human link back to the original (the citation target)
    version: str  # modified time / etag: unchanged version is skipped on re-sync


class Connector:
    name: ClassVar[str]
    label: ClassVar[str]

    def __init__(self, token: str, http: Http = default_http, **opts: str):
        if not token:
            raise ConnectorError("access token required")
        self.token, self.http, self.opts = token, http, opts

    def _get_json(self, url: str) -> dict:
        raw = self.http(url, {"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        try:
            return json.loads(raw)
        except ValueError as e:
            raise ConnectorError(f"non-JSON response from {url.split('?')[0]}") from e

    def items(self, limit: int = 50) -> Iterator[Item]:
        raise NotImplementedError
