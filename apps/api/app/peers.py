"""Peer discovery for a comps table: SEC companies with the same SIC code and a similar size.

Selection rule, stated in the output: SIC code equal to the target's (from the EDGAR company browse feed),
and latest full-year 10-K revenue between `low` and `high` times the target's revenue. Each peer is kept
with its CIK, its revenue and the companyfacts link it was selected from. Companies without a stated
revenue are dropped, never guessed.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app import edgar
from app.targets import sec_target

Fetch = Callable[[str], bytes]
BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=10-K&owner=include&count=100&output=atom&start={start}"
_ENTRY = re.compile(r"<cik>(\d+)</cik>.*?<sic>(\d+)</sic>", re.DOTALL)


@dataclass
class Peer:
    cik: str
    revenue: Decimal
    period: str
    source_url: str
    rule: str
    name: str = ""


def sic_companies(sic: str, pages: int, get: Fetch) -> list[str]:
    """CIKs from the browse feed for one SIC code, `pages` pages of 100."""
    out: list[str] = []
    for i in range(pages):
        body = get(BROWSE.format(sic=sic, start=i * 100)).decode("latin-1")
        found = [cik for cik, s in _ENTRY.findall(body) if s == sic]
        if not found:
            break
        out += [c for c in found if c not in out]
        time.sleep(0.2)  # SEC asks for no more than ten requests a second
    return out


def discover(target_revenue: Decimal, sic: str, exclude: set[str], pages: int = 3, low: Decimal = Decimal("0.5"),
             high: Decimal = Decimal(2), min_year: int = 2024, get: Fetch | None = None,
             facts_get: Fetch | None = None, want: int = 10) -> list[Peer]:
    """Up to `want` peers from `pages` pages of the SIC feed (100 companies a page), in feed order."""
    peers: list[Peer] = []
    for cik in sic_companies(sic, pages, get or edgar._default_get):
        if len(peers) >= want:
            break
        if cik.zfill(10) in {e.zfill(10) for e in exclude}:
            continue
        try:
            facts = edgar.fetch_companyfacts(cik, facts_get)
        except (OSError, ValueError):
            continue
        t = sec_target({"cik": cik, "name": facts.get("entityName", cik)}, facts)
        time.sleep(0.2)
        if t.revenue is None or not (target_revenue * low <= t.revenue <= target_revenue * high):
            continue
        if not t.revenue_period or int(t.revenue_period[2:6]) < min_year:
            continue  # stale revenue would compare different years
        peers.append(Peer(cik.zfill(10), t.revenue, t.revenue_period, t.revenue_url or "",
                          f"SIC {sic}; latest 10-K revenue {low}x to {high}x of target, FY {min_year} or later",
                          facts.get("entityName", "")))
    return peers
