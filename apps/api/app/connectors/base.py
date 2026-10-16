"""Connector contract. A connector only lists and downloads; ingestion, deal walls and citation
records are handled once, in `sync`, so no connector can bypass them.

HTTP is injectable (`Http`) so tests and offline demos replay recorded responses.
Credentials are passed per call and never stored by this layer.
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import ClassVar

Http = Callable[[str, dict[str, str]], bytes]


def default_http(url: str, headers: dict[str, str]) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("connectors only call https URLs")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


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
