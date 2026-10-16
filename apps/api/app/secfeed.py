"""SEC submissions + ticker lookup. Pure parsing plus a fetcher with the required User-Agent.

Every filing record carries its canonical archive URL so downstream facts can cite it.
The network call is injectable; tests run on saved real responses.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], bytes]
INTERESTING = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "40-F", "S-1", "S-1/A"}


@dataclass(frozen=True)
class Filing:
    cik: str
    accession: str
    form: str
    filed: str
    report_date: str
    primary_document: str
    url: str


def lookup_cik(tickers_doc: dict, ticker: str) -> tuple[str, str] | None:
    """Return (10-digit CIK, title). Case-insensitive; dotted/dashed class shares are kept as given."""
    t = ticker.strip().upper()
    for row in tickers_doc.values():
        if row["ticker"].upper() == t:
            return f"{int(row['cik_str']):010d}", row["title"]
    return None


def parse_submissions(doc: dict, forms: set[str] | None = INTERESTING) -> list[Filing]:
    """Recent filings only (older pages are listed in filings.files and are not followed here)."""
    cik = f"{int(doc['cik']):010d}"
    r = doc.get("filings", {}).get("recent", {})
    out = []
    for i, acc in enumerate(r.get("accessionNumber", [])):
        form = r["form"][i]
        if forms is not None and form not in forms:
            continue
        prim = r["primaryDocument"][i]
        # Inline XBRL viewer paths (xsl.../) are not the raw document; strip the viewer prefix.
        raw = prim.split("/", 1)[1] if prim.startswith("xsl") and "/" in prim else prim
        out.append(Filing(cik, acc, form, r["filingDate"][i], r.get("reportDate", [""] * 99)[i] or "",
                          raw, f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{raw}"))
    return out


def default_fetch(url: str) -> bytes:
    import urllib.request
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise RuntimeError("SEC_USER_AGENT env var required (SEC rejects requests without contact info)")
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def recent_filings(ticker: str, fetch: Fetch = default_fetch) -> list[Filing]:
    hit = lookup_cik(json.loads(fetch("https://www.sec.gov/files/company_tickers.json")), ticker)
    if not hit:
        return []
    return parse_submissions(json.loads(fetch(f"https://data.sec.gov/submissions/CIK{hit[0]}.json")))
