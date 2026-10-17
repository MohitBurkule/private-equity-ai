"""Live sourcing search on EDGAR full-text search. Finds companies that are not in the imported universe.

Each candidate carries the filing it was found in (company browse link and filing URL), so every match is
cited. Nothing is imported here: the caller decides which candidates to add through the normal import.
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], str]
SEARCH = "https://efts.sec.gov/LATEST/search-index"


@dataclass
class Candidate:
    name: str
    cik: str  # zero-padded to 10 digits, as the SEC target import stores it
    sic: str | None
    form: str
    file_date: str
    filing_url: str
    company_url: str


def _default_fetch(url: str) -> str:
    import os
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": os.environ.get("SEC_USER_AGENT", "")})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def parse(payload: dict) -> list[Candidate]:
    out: dict[str, Candidate] = {}
    for h in payload.get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        ciks, names = s.get("ciks") or [], s.get("display_names") or []
        if not ciks or not names or not s.get("adsh"):
            continue
        cik = ciks[0].zfill(10)
        if cik in out:
            continue
        raw_cik = str(int(cik))
        adsh = s["adsh"].replace("-", "")
        out[cik] = Candidate(
            name=names[0].split("  (")[0].strip(), cik=cik, sic=(s.get("sics") or [None])[0],
            form=s.get("form", ""), file_date=s.get("file_date", ""),
            filing_url=f"https://www.sec.gov/Archives/edgar/data/{raw_cik}/{adsh}/",
            company_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={raw_cik}")
    return list(out.values())


def search(query: str, forms: list[str], since: str, until: str, fetch: Fetch = _default_fetch) -> list[Candidate]:
    found: dict[str, Candidate] = {}
    for form in forms:
        q = urllib.parse.urlencode({"q": f'"{query}"', "forms": form, "startdt": since, "enddt": until})
        for c in parse(json.loads(fetch(f"{SEARCH}?{q}"))):
            found.setdefault(c.cik, c)
    return list(found.values())
