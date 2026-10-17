"""Revenue check for watched candidates. SEC companies are checked against their companyfacts (the same
rule the SEC target import uses); Companies House companies are marked unverified because their revenue
sits in iXBRL accounts this check does not read. Anything not found is unverified, never estimated."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app import edgar
from app.targets import sec_target

_CIK_IN_URL = re.compile(r"/edgar/data/(\d+)/")


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


def check_url(url: str, name: str, get: edgar.Getter | None = None) -> Check:
    m = _CIK_IN_URL.search(url)
    if not m:
        return Check("unverified", note="no SEC CIK in the source link; Companies House accounts not read here")
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
