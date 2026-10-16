"""Deal-announcement scan over SEC full-text search: seeds for precedent-transaction work, no key needed.

Finds 8-Ks mentioning a phrase (default: a merger agreement). A hit is a lead, not a deal record: terms, multiples
and parties must be read from the cited filing. The efts endpoint is undocumented and can change; failures raise.
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from app.secfeed import default_fetch

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Lead:
    company: str
    cik: str
    filed: str
    form: str
    items: tuple[str, ...]
    accession: str
    url: str


def parse(doc: dict) -> list[Lead]:
    out = []
    for h in doc["hits"]["hits"]:
        s = h["_source"]
        acc, _, fname = h["_id"].partition(":")
        cik = str(s["ciks"][0]).lstrip("0")
        out.append(Lead(s["display_names"][0], s["ciks"][0], s["file_date"], s["form"], tuple(s.get("items") or ()),
                        acc, f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fname}"))
    return out


def scan(since: str, until: str, phrase: str = "agreement and plan of merger", form: str = "8-K",
         fetch: Fetch = default_fetch) -> list[Lead]:
    q = urllib.parse.urlencode({"q": f'"{phrase}"', "forms": form, "startdt": since, "enddt": until})
    return parse(json.loads(fetch(f"https://efts.sec.gov/LATEST/search-index?{q}")))
