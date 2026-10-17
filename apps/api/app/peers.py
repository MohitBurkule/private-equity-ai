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
from dataclasses import dataclass, replace
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
    matched_on: str = "sic"  # "sic" = target's own code; "sic_group" = another code in its major group


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


def group_codes(sic: str) -> list[str]:
    """Other four-digit SIC codes in the same three-digit family (7370 to 7379 for 7372). The browse feed takes
    exact codes only, so each code is queried on its own. Checked live: 7370 to 7374 and 7377 return companies."""
    return [sic[:3] + d for d in "0123456789" if sic[:3] + d != sic]


@dataclass(frozen=True)
class PeerRule:
    low: Decimal = Decimal("0.5")
    high: Decimal = Decimal(2)
    min_year: int = 2024
    min_peers: int = 3
    widen: bool = True  # False: exact SIC code only, never the family


_BAND = re.compile(r"\bband\s*[=:]\s*(\d+(?:\.\d+)?)\s*x?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*x?", re.IGNORECASE)
_MIN_PEERS = re.compile(r"\bmin\s*peers\s*[=:]\s*(\d+)", re.IGNORECASE)
_MIN_YEAR = re.compile(r"\bmin\s*year\s*[=:]\s*(\d{4})", re.IGNORECASE)
_FAMILY = re.compile(r"\bfamily\s*[=:]\s*(yes|no)\b", re.IGNORECASE)


def parse_rule(text: str) -> PeerRule:
    """Firm peer rule, e.g. "band: 0.4 to 2.5; min peers: 4; min year: 2025; family: no".
    Anything the rule does not state keeps the default, so an empty rule is the standard selection."""
    d = PeerRule()
    if m := _BAND.search(text):
        d = replace(d, low=Decimal(m.group(1)), high=Decimal(m.group(2)))
    if m := _MIN_PEERS.search(text):
        d = replace(d, min_peers=int(m.group(1)))
    if m := _MIN_YEAR.search(text):
        d = replace(d, min_year=int(m.group(1)))
    if m := _FAMILY.search(text):
        d = replace(d, widen=m.group(1).lower() == "yes")
    return d


def discover_with_group(target_revenue: Decimal, sic: str, exclude: set[str], pages: int = 3,
                        rule: PeerRule | None = None, get: Fetch | None = None, facts_get: Fetch | None = None,
                        want: int = 10) -> list[Peer]:
    """Exact-SIC peers first. When fewer than `rule.min_peers` pass and the rule allows it, widen to the other
    codes in the same SIC family. Every widened peer is tagged `matched_on="sic_group"` and its rule names the family."""
    rule = rule or PeerRule()
    band = {"low": rule.low, "high": rule.high, "min_year": rule.min_year}
    found = discover(target_revenue, sic, exclude, pages=pages, get=get, facts_get=facts_get, want=want, **band)
    if len(found) >= rule.min_peers or not rule.widen:
        return found
    seen = set(exclude) | {p.cik.zfill(10) for p in found}
    for code in group_codes(sic):
        if len(found) >= want:
            break
        more = discover(target_revenue, code, seen, pages=1, get=get, facts_get=facts_get,
                        want=want - len(found), **band)
        for p in more:
            seen.add(p.cik)
            found.append(replace(p, matched_on="sic_group", rule=f"{p.rule} (SIC family {sic[:3]})"))
    return found


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


def peer_items(found: list[Peer]) -> list[dict]:
    """JSON-ready rows for a stored peer set."""
    return [{"cik": p.cik, "name": p.name, "revenue": str(p.revenue), "period": p.period,
             "source_url": p.source_url, "rule": p.rule, "matched_on": p.matched_on} for p in found]


def refresh_items(items: list[dict], min_year: int = 2024, facts_get: Fetch | None = None) -> tuple[list[dict], list[dict]]:
    """Re-read each stored peer's latest 10-K revenue from EDGAR companyfacts. Returns (kept, dropped).
    A peer with no stated revenue, or whose latest revenue is older than `min_year`, is dropped with its reason."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for it in items:
        try:
            facts = edgar.fetch_companyfacts(it["cik"], facts_get)
        except (OSError, ValueError) as e:
            dropped.append({"cik": it["cik"], "name": it["name"], "reason": f"fetch failed: {e}"})
            continue
        t = sec_target({"cik": it["cik"], "name": facts.get("entityName", it["name"])}, facts)
        time.sleep(0.2)
        if t.revenue is None or not t.revenue_period or int(t.revenue_period[2:6]) < min_year:
            dropped.append({"cik": it["cik"], "name": it["name"], "reason": "no current 10-K revenue"})
            continue
        kept.append({**it, "name": facts.get("entityName", it["name"]), "revenue": str(t.revenue),
                     "period": t.revenue_period, "source_url": t.revenue_url or it["source_url"]})
    return kept, dropped
