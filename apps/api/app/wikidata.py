"""Wikidata entity search (CC0): ids, labels and descriptions to disambiguate companies and firms.

Wikimedia throttles bursts, so one call per lookup, descriptive User-Agent, and HTTP 429 raises instead of retrying.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Hit:
    qid: str
    label: str
    description: str
    url: str


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1 (https://github.com/MohitBurkule/private-equity-ai)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def parse(doc: dict) -> list[Hit]:
    return [Hit(h["id"], h.get("label", ""), h.get("description", ""), f"https://www.wikidata.org/wiki/{h['id']}")
            for h in doc.get("search", [])]


def search(name: str, limit: int = 5, fetch: Fetch = default_fetch) -> list[Hit]:
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": name, "language": "en", "format": "json",
                                "limit": limit})
    return parse(json.loads(fetch(f"https://www.wikidata.org/w/api.php?{q}")))
