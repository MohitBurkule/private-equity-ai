"""GLEIF LEI lookup (CC0, no key): legal entity identity and parent links, an open stand-in for Orbis/CapIQ hierarchy.

Coverage is regulated and larger entities that hold an LEI, not every private company. Each Entity carries the
record's own URL so it can be cited.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], bytes]
BASE = "https://api.gleif.org/api/v1/lei-records"


@dataclass(frozen=True)
class Entity:
    lei: str
    name: str
    country: str
    status: str
    registration: str
    headquarters_city: str
    direct_parent_url: str | None
    ultimate_parent_url: str | None
    url: str


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1", "Accept": "application/vnd.api+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _related(rel: dict, key: str) -> str | None:
    return ((rel.get(key) or {}).get("links") or {}).get("lei-record")


def parse(doc: dict) -> list[Entity]:
    out = []
    for rec in doc.get("data", []):
        a, rel = rec["attributes"], rec.get("relationships", {})
        e = a["entity"]
        name = e["legalName"]["name"] if isinstance(e["legalName"], dict) else e["legalName"]
        out.append(Entity(rec["id"], name, (e.get("legalAddress") or {}).get("country") or "",
                          e.get("status") or "", (a.get("registration") or {}).get("status") or "",
                          (e.get("headquartersAddress") or {}).get("city") or "",
                          _related(rel, "direct-parent"), _related(rel, "ultimate-parent"),
                          f"{BASE}/{rec['id']}"))
    return out


def search(name: str, limit: int = 5, fetch: Fetch = default_fetch) -> list[Entity]:
    q = urllib.parse.urlencode({"filter[entity.legalName]": name, "page[size]": limit})
    return parse(json.loads(fetch(f"{BASE}?{q}")))
