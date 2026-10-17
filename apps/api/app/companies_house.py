"""Companies House company lookup. Uses the REST API when CH_API_KEY is set, else the public
find-and-update page (keyless, scrape-only). Both paths return the same CompanyRecord, so callers
never need to know which one answered. Keyless pages are HTML that Companies House can change
without notice, so the parser only trusts the element ids it finds and leaves anything missing as None.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape

API_BASE = "https://api.company-information.service.gov.uk"
WEB_BASE = "https://find-and-update.company-information.service.gov.uk"
# Companies House asks for a descriptive UA; a bare default is commonly blocked.
USER_AGENT = "private-equity-ai demo (+https://github.com/MohitBurkule/private-equity-ai)"


@dataclass
class CompanyRecord:
    number: str
    name: str | None
    status: str | None
    company_type: str | None
    incorporated: str | None
    sic: list[str]
    source: str  # "api" or "web": where the figures came from, for the source link


def _text(html: str, element_id: str) -> str | None:
    m = re.search(rf'id="{re.escape(element_id)}"[^>]*>(.*?)</', html, re.DOTALL)
    if not m:
        return None
    value = " ".join(unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
    return value or None


def parse_company_page(html: str, number: str) -> CompanyRecord:
    h1 = re.search(r'<h1[^>]*class="heading-xlarge"[^>]*>(.*?)</h1>', html, re.DOTALL)
    name = " ".join(unescape(re.sub(r"<[^>]+>", " ", h1.group(1))).split()) if h1 else None
    sic = [s for s in (_text(html, f"sic{i}") for i in range(10)) if s]
    return CompanyRecord(
        number=number,
        name=name or None,
        status=_text(html, "company-status"),
        company_type=_text(html, "company-type-value"),
        incorporated=_text(html, "company-creation-date"),
        sic=sic,
        source="web",
    )


def parse_company_api(body: dict, number: str) -> CompanyRecord:
    return CompanyRecord(
        number=number,
        name=body.get("company_name"),
        status=body.get("company_status"),
        company_type=body.get("type"),
        incorporated=body.get("date_of_creation"),
        sic=list(body.get("sic_codes") or []),
        source="api",
    )


def _get(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_company(number: str, api_key: str | None = None) -> CompanyRecord | None:
    """Returns None for an unknown company number, so the caller can say so instead of guessing."""
    api_key = api_key if api_key is not None else os.getenv("CH_API_KEY")
    number = number.strip().upper()
    try:
        if api_key:
            token = base64.b64encode(f"{api_key}:".encode()).decode()
            body = json.loads(_get(f"{API_BASE}/company/{number}", {"Authorization": f"Basic {token}"}))
            return parse_company_api(body, number)
        html = _get(f"{WEB_BASE}/company/{number}", {}).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return parse_company_page(html, number)


def company_numbers_to_targets(numbers: list[str], fetch=fetch_company) -> tuple[list, list[str]]:
    """Targets for company numbers the caller supplies. Dissolved or unknown numbers are returned
    as `skipped`, not imported, so a stale list cannot quietly become a live target set."""
    from app.targets import TargetIn, uk_sector

    items, skipped = [], []
    for raw in numbers:
        rec = fetch(raw)
        if rec is None or not rec.name or (rec.status or "").lower() != "active":
            skipped.append(raw.strip().upper())
            continue
        sic = rec.sic[0].split(" - ")[0] if rec.sic else None
        items.append(TargetIn(rec.name, "companies_house", rec.number,
                              f"{WEB_BASE}/company/{rec.number}",
                              uk_sector(sic), sic, "United Kingdom", None))
    return items, skipped
