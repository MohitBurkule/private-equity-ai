"""Revenue check for watched candidates. SEC companies are checked against their companyfacts (the same
rule the SEC target import uses). Companies House companies are checked against the latest accounts filed
with an iXBRL document, read with the tagged Turnover line; that needs CH_API_KEY, so without it the check
says so. Anything not found is unverified, never estimated."""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app import edgar
from app.ixbrl import read_ixbrl
from app.targets import sec_target

_CIK_IN_URL = re.compile(r"/edgar/data/(\d+)/")
_CH_NUMBER_IN_URL = re.compile(r"/company/([A-Za-z0-9]+)")
CH_API = "https://api.company-information.service.gov.uk"
CH_DOCS = "https://document-api.company-information.service.gov.uk"
ChGetter = Callable[[str, dict[str, str]], bytes]


@dataclass
class Check:
    status: str  # verified | unverified
    revenue: Decimal | None = None
    period: str | None = None
    source_url: str | None = None
    note: str = ""

    def text(self) -> str:
        if self.status == "verified":
            return f"Revenue {self.revenue} for {self.period} (SEC companyfacts, {self.source_url})"
        return f"Revenue unverified: {self.note}"


def _ch_get(url: str, headers: dict[str, str]) -> bytes:
    key = os.environ.get("CH_API_KEY", "")
    req = urllib.request.Request(url, headers={
        **headers, "Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:  # fixed Companies House hosts only
        return r.read()


def check_ch(number: str, name: str, get: ChGetter | None = None) -> Check:
    """Tagged Turnover from the latest accounts document on the Companies House filing history."""
    if get is None and not os.environ.get("CH_API_KEY"):
        return Check("unverified", note="Companies House accounts need CH_API_KEY")
    get = get or _ch_get
    try:
        hist = json.loads(get(f"{CH_API}/company/{number}/filing-history?category=accounts&items_per_page=10",
                              {"Accept": "application/json"}))
        docs = [i["links"]["document_metadata"] for i in hist.get("items", []) if i.get("links", {}).get("document_metadata")]
        if not docs:
            return Check("unverified", note="no accounts document on the filing history")
        body = get(f"{docs[0]}/content", {"Accept": "application/xhtml+xml"}).decode("utf-8", errors="replace")
    except (OSError, ValueError, KeyError) as e:
        return Check("unverified", note=f"Companies House accounts unavailable ({type(e).__name__})")
    rep = read_ixbrl(body)
    if "Turnover" not in rep.pnl or not rep.pnl_period:
        return Check("unverified", note="latest accounts carry no tagged turnover (micro or abridged filing)")
    filings = f"https://find-and-update.company-information.service.gov.uk/company/{number}/filing-history"
    return Check("verified", rep.pnl["Turnover"], rep.pnl_period, filings)


def check_url(url: str, name: str, get: edgar.Getter | None = None) -> Check:
    m = _CIK_IN_URL.search(url)
    if not m:
        ch = _CH_NUMBER_IN_URL.search(url)
        if ch and "company-information" in url:
            return check_ch(ch.group(1), name, get=None)
        return Check("unverified", note="no SEC CIK or Companies House number in the source link")
    try:
        facts = edgar.fetch_companyfacts(m.group(1), get)
    except (OSError, ValueError) as e:
        return Check("unverified", note=f"companyfacts unavailable ({type(e).__name__})")
    t = sec_target({"cik": m.group(1), "name": name}, facts)
    if t.revenue is None:
        return Check("unverified", note="no full-year 10-K revenue in companyfacts")
    return Check("verified", t.revenue, t.revenue_period, t.revenue_url)


def ebitda_margin_clause(text: str) -> Decimal | None:
    """'EBITDA margin is at least 15%' -> 15. Margins are not stored on targets, so the screen reports
    this criterion as not applied rather than passing or failing it."""
    m = re.search(r"EBITDA\s+margin\s+(?:is\s+)?at\s+least\s+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    return Decimal(m.group(1)) if m else None
