"""Scores new filings against a firm thesis: SIC division, keyword and revenue band. Each criterion that is met
cites the filing it came from. A criterion the filing does not show counts as unmet, with the reason, never as met.

The filings are passed in with their text and revenue already fetched, so this module makes no network calls and
the score can be re-run on the same inputs later. Ranking shows the criteria met, not an investment view.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Thesis:
    sic_divisions: frozenset[str] = frozenset()
    keywords: tuple[str, ...] = ()
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None


@dataclass(frozen=True)
class Filing:
    url: str
    name: str
    sic: str | None = None
    text: str = ""
    revenue: Decimal | None = None


def _keyword_cite(text: str, keyword: str) -> str | None:
    m = re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE)
    if m is None:
        return None
    return " ".join(text[max(0, m.start() - 60): m.end() + 60].split())


def score(thesis: Thesis, f: Filing) -> dict:
    criteria = []
    if thesis.sic_divisions:
        met = bool(f.sic) and f.sic[:2] in thesis.sic_divisions
        criteria.append({"criterion": "sic_division", "met": met,
                         "reason": None if f.sic else "no SIC code on the filing",
                         "cite": f"SIC {f.sic} ({f.url})" if met else None})
    for kw in thesis.keywords:
        snippet = _keyword_cite(f.text, kw)
        criteria.append({"criterion": f"keyword:{kw}", "met": snippet is not None,
                         "reason": None if snippet is not None else "not in the filing text",
                         "cite": f'"{snippet}" ({f.url})' if snippet else None})
    if thesis.min_revenue is not None or thesis.max_revenue is not None:
        in_band = f.revenue is not None and (thesis.min_revenue is None or f.revenue >= thesis.min_revenue) \
            and (thesis.max_revenue is None or f.revenue <= thesis.max_revenue)
        criteria.append({"criterion": "revenue_band", "met": in_band,
                         "reason": None if f.revenue is not None else "no revenue figure in the filing",
                         "cite": f"revenue {f.revenue} ({f.url})" if f.revenue is not None else None})
    met_n = sum(c["met"] for c in criteria)
    return {"name": f.name, "url": f.url, "met": met_n, "of": len(criteria),
            "score": (met_n / len(criteria)) if criteria else 0.0, "criteria": criteria}


def rank(thesis: Thesis, filings: list[Filing]) -> list[dict]:
    """Best match first; ties keep input order, so a rerun on the same inputs gives the same list."""
    scored = [score(thesis, f) for f in filings]
    return sorted(scored, key=lambda s: -s["score"])
