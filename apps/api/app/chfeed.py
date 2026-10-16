"""Companies House filing list (REST API, needs a free API key in COMPANIES_HOUSE_API_KEY).

The key is sent as the Basic-auth user name with an empty password, as the API requires. The network
call is injectable. Tests use SYNTHETIC fixtures shaped from the published API reference, because no
keyed responses were available when this was written; they must be replaced with real saved
responses once a key exists.
"""
from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], bytes]
_NUMBER = re.compile(r"^[A-Z0-9]{8}$")
BASE = "https://api.company-information.service.gov.uk"


class CompanyNotFound(Exception):
    pass


@dataclass(frozen=True)
class AccountsFiling:
    company_number: str
    transaction_id: str
    filed: str
    period_end: str
    kind: str  # e.g. accounts type from the description
    description: str
    document_metadata_url: str


def normalise_number(n: str) -> str:
    """Company numbers are 8 characters; purely numeric ones are zero-padded ('1234' -> '00001234')."""
    n = n.strip().upper()
    if n.isdigit():
        n = n.zfill(8)
    if not _NUMBER.match(n):
        raise ValueError("company number must be 8 letters or digits (numeric numbers are zero-padded)")
    return n


def parse_filing_history(doc: dict, number: str) -> list[AccountsFiling]:
    out = []
    for it in doc.get("items", []):
        if it.get("category") != "accounts":
            continue
        meta = (it.get("links") or {}).get("document_metadata", "")
        period = (it.get("description_values") or {}).get("made_up_date", "")
        out.append(AccountsFiling(number, it.get("transaction_id", ""), it.get("date", ""), period,
                                  it.get("type", ""), it.get("description", ""),
                                  f"https://document-api.company-information.service.gov.uk{meta}" if meta.startswith("/") else meta))
    return out


def default_fetch(url: str) -> bytes:
    import urllib.error
    import urllib.request
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        raise RuntimeError("COMPANIES_HOUSE_API_KEY env var required")
    token = base64.b64encode(f"{key}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise CompanyNotFound(url) from e
        raise


def accounts_filings(number: str, fetch: Fetch = default_fetch) -> list[AccountsFiling]:
    n = normalise_number(number)
    raw = fetch(f"{BASE}/company/{n}/filing-history?category=accounts&items_per_page=100")
    return parse_filing_history(json.loads(raw), n)
