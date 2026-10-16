"""Fund and investment return metrics from dated cash flows. Pure code; inputs are the caller's.

Sign convention: contributions (money paid in) are negative, distributions are positive, as an LP sees
them. `nav` is the remaining value at `as_of`. IRR is XIRR on actual/365 days. When the flows cannot
produce an IRR (no sign change, or no root found) the result says so; it never returns a made-up number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class FundMetrics:
    paid_in: Decimal
    distributed: Decimal
    nav: Decimal
    dpi: Decimal | None
    rvpi: Decimal | None
    tvpi: Decimal | None
    irr: float | None
    irr_note: str = ""


def _xnpv(rate: float, flows: list[tuple[date, float]]) -> float:
    t0 = flows[0][0]
    return sum(a / (1 + rate) ** ((d - t0).days / 365) for d, a in flows)


def xirr(flows: list[tuple[date, float]]) -> tuple[float | None, str]:
    flows = sorted(flows)
    if len(flows) < 2:
        return None, "needs at least two dated flows"
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None, "needs both a payment in and a payment out (or a positive NAV)"
    if flows[0][0] == flows[-1][0]:
        return None, "all flows on one date"
    lo, hi = -0.999999, 1e6
    f_lo, f_hi = _xnpv(lo, flows), _xnpv(hi, flows)
    if f_lo * f_hi > 0:
        return None, "no rate found that makes the flows net to zero"
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = _xnpv(mid, flows)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2, ""


def fund_metrics(flows: list[tuple[date, Decimal]], nav: Decimal, as_of: date) -> FundMetrics:
    if nav < 0:
        raise ValueError("nav cannot be negative")
    if any(d > as_of for d, _ in flows):
        raise ValueError("a cash flow is dated after as_of")
    paid = -sum((a for _, a in flows if a < 0), Decimal(0))
    dist = sum((a for _, a in flows if a > 0), Decimal(0))
    dpi = dist / paid if paid else None
    rvpi = nav / paid if paid else None
    tvpi = (dist + nav) / paid if paid else None
    series = [(d, float(a)) for d, a in flows] + ([(as_of, float(nav))] if nav else [])
    irr, note = xirr(series)
    return FundMetrics(paid, dist, nav, dpi, rvpi, tvpi, irr, note)


@dataclass
class Cohort:
    vintage: int
    funds: int
    paid_in: Decimal
    distributed: Decimal
    nav: Decimal
    pooled_tvpi: Decimal | None
    median_tvpi: Decimal | None  # None when any fund in the cohort has nothing paid in


def vintage_cohorts(funds: list[tuple[str, int, list[tuple[date, Decimal]], Decimal]], as_of: date) -> list[Cohort]:
    """Group funds (name, vintage year, flows, nav) by vintage. Pooled TVPI sums money, then divides."""
    by: dict[int, list[FundMetrics]] = {}
    for _name, vintage, flows, nav in funds:
        by.setdefault(vintage, []).append(fund_metrics(flows, nav, as_of))
    out = []
    for v in sorted(by):
        ms = by[v]
        paid = sum((m.paid_in for m in ms), Decimal(0))
        dist = sum((m.distributed for m in ms), Decimal(0))
        nav = sum((m.nav for m in ms), Decimal(0))
        tv = sorted(m.tvpi for m in ms if m.tvpi is not None)
        med = None
        if len(tv) == len(ms):
            mid = len(tv) // 2
            med = tv[mid] if len(tv) % 2 else (tv[mid - 1] + tv[mid]) / 2
        out.append(Cohort(v, len(ms), paid, dist, nav, (dist + nav) / paid if paid else None, med))
    return out
