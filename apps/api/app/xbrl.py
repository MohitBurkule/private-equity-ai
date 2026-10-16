"""SEC companyfacts lookup and numeric cross-check.

Used as ground truth for numbers extracted from filing text: a figure read from a table
can be confirmed (or contradicted) against the filer's own XBRL, deterministically.
Handles duplicates (same value reported in many filings) and restatements (same period,
different values across vintages). Never picks silently when vintages disagree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class XFact:
    concept: str
    start: str | None
    end: str
    value: Decimal
    accn: str
    form: str
    filed: str
    unit: str


def load_companyfacts(doc: dict) -> list[XFact]:
    out = []
    for taxonomy, concepts in doc.get("facts", {}).items():
        for name, body in concepts.items():
            for unit, rows in body.get("units", {}).items():
                for r in rows:
                    out.append(XFact(f"{taxonomy}:{name}", r.get("start"), r["end"], Decimal(str(r["val"])),
                                     r.get("accn", ""), r.get("form", ""), r.get("filed", ""), unit))
    return out


_CTX_DUR = re.compile(r"(\d{2})_(\d{2})_(\d{4})To(\d{2})_(\d{2})_(\d{4})")
_CTX_INST = re.compile(r"AsOn(\d{2})_(\d{2})_(\d{4})")


def period_from_context(ctx: str) -> tuple[str | None, str] | None:
    """Parse common contextRef spellings like P01_01_2025To12_31_2025 / PAsOn12_31_2025."""
    m = _CTX_DUR.search(ctx)
    if m:
        a, b, c, d, e, f = m.groups()
        return f"{c}-{a}-{b}", f"{f}-{d}-{e}"
    m = _CTX_INST.search(ctx)
    if m:
        a, b, c = m.groups()
        return None, f"{c}-{a}-{b}"
    return None


def candidates(facts: list[XFact], concept: str, end: str, start: str | None = None,
               accn: str | None = None, unit: str | None = "USD") -> list[XFact]:
    """unit=None matches any unit (e.g. USD/shares for EPS, shares, pure)."""
    return [f for f in facts if f.concept == concept and f.end == end and (unit is None or f.unit == unit)
            and (start is None or f.start == start) and (accn is None or f.accn == accn)]


@dataclass(frozen=True)
class CheckResult:
    status: str  # match | restated | mismatch | not_found
    matched: list[XFact]
    distinct_values: list[Decimal]


def crosscheck(claimed: Decimal, cands: list[XFact]) -> CheckResult:
    if not cands:
        return CheckResult("not_found", [], [])
    values = sorted({c.value for c in cands})
    hits = [c for c in cands if c.value == claimed]
    if hits and len(values) > 1:  # claimed matches one vintage but vintages disagree: say so
        return CheckResult("restated", hits, values)
    if hits:
        return CheckResult("match", hits, values)
    return CheckResult("mismatch", [], values)
