"""Companies House live name search for candidates outside the imported set.

Public HTML search page by default; the JSON API only when CH_API_KEY is set. Requests are spaced at
least RATE_SECONDS apart. The site publishes no robots.txt (404 when checked), so there are no
disallowed paths to honour; the spacing is ours. Each candidate links to its own company page.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], str]
WEB = "https://find-and-update.company-information.service.gov.uk"
API = "https://api.company-information.service.gov.uk"
RATE_SECONDS = 2.0
UA = "private-equity-ai research (+https://github.com/MohitBurkule/private-equity-ai)"
_last = [0.0]


@dataclass
class Candidate:
    name: str
    number: str
    status: str | None
    address: str | None
    company_url: str


def _get(url: str, headers: dict[str, str] | None = None) -> str:
    gap = RATE_SECONDS - (time.monotonic() - _last[0])
    if gap > 0:
        time.sleep(gap)
    _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


_CARD = re.compile(r'<li class="type-company">(.*?)</li>', re.DOTALL)
_LINK = re.compile(r'<a class="govuk-link" href="/company/([0-9A-Za-z]+)"[^>]*>\s*(.*?)\s*</a>', re.DOTALL)
_META = re.compile(r'<p class="meta crumbtrail">\s*(.*?)\s*</p>', re.DOTALL)
_ADDR = re.compile(r"</p>\s*<p>\s*(.*?)\s*</p>", re.DOTALL)


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_html(page: str) -> list[Candidate]:
    out = []
    for card in _CARD.findall(page):
        m = _LINK.search(card)
        if not m:
            continue
        meta = _META.search(card)
        meta_text = _clean(meta.group(1)) if meta else ""
        number, _, rest = meta_text.partition(" - ")
        number = number.strip() or m.group(1)
        status = rest.split(" on ")[0].strip() or None
        addr = _ADDR.search(card)
        out.append(Candidate(_clean(m.group(2)), number, status, _clean(addr.group(1)) if addr else None,
                             f"{WEB}/company/{m.group(1)}"))
    return out


def parse_api(payload: dict) -> list[Candidate]:
    out = []
    for it in payload.get("items", []):
        if it.get("kind") != "searchresults#company" and "company_number" not in it:
            continue
        out.append(Candidate(it.get("title", ""), it["company_number"], it.get("company_status"),
                             (it.get("address_snippet") or None), f"{WEB}/company/{it['company_number']}"))
    return out


def search(query: str, limit: int = 20, fetch: Fetch | None = None) -> list[Candidate]:
    key = os.environ.get("CH_API_KEY")
    if key:
        token = base64.b64encode(f"{key}:".encode()).decode()
        fetch = fetch or (lambda u: _get(u, {"Authorization": f"Basic {token}"}))
        q = urllib.parse.urlencode({"q": query, "items_per_page": min(max(limit, 1), 100)})
        return parse_api(json.loads(fetch(f"{API}/search/companies?{q}")))[:limit]
    fetch = fetch or _get
    q = urllib.parse.urlencode({"q": query})
    return parse_html(fetch(f"{WEB}/search/companies?{q}"))[:limit]
