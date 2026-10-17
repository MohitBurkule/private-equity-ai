"""Sanctions screening against an OpenSanctions simple-CSV export (no key for bulk files).

Source: https://data.opensanctions.org/datasets/latest/<dataset>/targets.simple.csv (e.g. us_ofac_sdn). LICENCE: the
OpenSanctions bulk data is understood to be CC BY-NC 4.0, so commercial use needs their licence (NOT verified in this
build; check before shipping hosted). The upstream OFAC list itself is a US government publication.

This is a screening aid, never a clearance: a miss only means no name match in THIS export on THIS date. Matching is on
normalised names and aliases (case, accents, punctuation, word order), returns candidates with the reason, and the
caller must confirm identity from the listed birth date, country and identifiers.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    name: str
    aliases: tuple[str, ...]
    birth_date: str
    countries: str
    sanctions: str
    dataset: str
    last_seen: str
    url: str


@dataclass(frozen=True)
class Match:
    entry: Entry
    matched_on: str
    how: str  # "exact" (same normalised string) or "tokens" (same words, any order)


def dataset_url(dataset: str) -> str:
    return f"https://data.opensanctions.org/datasets/latest/{dataset}/targets.simple.csv"


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def parse(text: str) -> list[Entry]:
    return [Entry(r["id"], r["schema"], r["name"], tuple(a for a in r["aliases"].split(";") if a), r["birth_date"],
                  r["countries"], r["sanctions"], r["dataset"], r["last_seen"],
                  f"https://www.opensanctions.org/entities/{r['id']}/")
            for r in csv.DictReader(io.StringIO(text))]


def load(dataset: str = "us_ofac_sdn", fetch: Fetch = default_fetch) -> list[Entry]:
    return parse(fetch(dataset_url(dataset)).decode("utf-8", "replace"))


def screen(entries: list[Entry], name: str) -> list[Match]:
    q = norm(name)
    if len(q) < 3:
        return []
    qt = sorted(q.split())
    out = []
    for e in entries:
        for cand in (e.name, *e.aliases):
            n = norm(cand)
            if n == q:
                out.append(Match(e, cand, "exact"))
                break
            if sorted(n.split()) == qt:
                out.append(Match(e, cand, "tokens"))
                break
    return out
