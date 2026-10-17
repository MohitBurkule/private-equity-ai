"""Fund distribution waterfall per LP: return of capital, preferred return, GP catch-up, then carried interest.

European (whole fund): every distribution goes through the tiers against all contributions made so far.
American (deal by deal): the same tiers run for each deal's own contributions and proceeds, with no clawback.
Terms are the caller's inputs and each carries its source (the LPA clause it came from). The preferred return
compounds annually on actual/365 days over capital and unpaid preferred return. Catch-up is a share of each dollar
in the catch-up tier (1 = full catch-up); with catch-up 0 there is no catch-up tier. Results add up to every
distribution exactly, to the cent; the rounding gap goes to the LP split. Per-LP amounts are pro rata to commitments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Terms:
    hurdle: Decimal  # annual preferred return, e.g. 0.08
    carry: Decimal  # GP share of profit, e.g. 0.20
    catchup: Decimal  # GP share of each dollar in the catch-up tier, 0 for none, up to 1
    source: str  # the LPA clause the three terms come from

    def __post_init__(self):
        if not (0 <= self.hurdle < 1 and 0 <= self.carry < 1):
            raise ValueError("hurdle and carry must be between 0 and 1")
        if not (self.catchup == 0 or self.carry < self.catchup <= 1):
            raise ValueError("catch-up must be 0 or above carry and at most 1")


@dataclass
class Flow:
    on: date
    amount: Decimal
    source: str  # the record the flow was read from


@dataclass
class Tiers:
    to_lp_capital: Decimal = ZERO
    to_lp_pref: Decimal = ZERO
    to_gp_catchup: Decimal = ZERO
    to_lp_catchup: Decimal = ZERO
    to_lp_split: Decimal = ZERO
    to_gp_split: Decimal = ZERO

    def lp(self) -> Decimal:
        return self.to_lp_capital + self.to_lp_pref + self.to_lp_catchup + self.to_lp_split

    def gp(self) -> Decimal:
        return self.to_gp_catchup + self.to_gp_split

    def add(self, o: Tiers) -> None:
        for k in self.__dataclass_fields__:
            setattr(self, k, getattr(self, k) + getattr(o, k))


@dataclass
class Step:
    on: date
    amount: Decimal
    source: str
    tiers: Tiers


@dataclass
class Result:
    steps: list[Step] = field(default_factory=list)
    totals: Tiers = field(default_factory=Tiers)


def _accrue(days: int, base: Decimal, h: Decimal) -> Decimal:
    return base * ((1 + h) ** (Decimal(days) / Decimal(365)) - 1)


def run(flows: list[Flow], dists: list[Flow], terms: Terms) -> Result:
    if any(f.amount <= 0 for f in flows + dists):
        raise ValueError("amounts are positive; contributions and distributions are separate lists")
    events = sorted([(f.on, 0, f) for f in flows] + [(d.on, 1, d) for d in dists], key=lambda e: (e[0], e[1]))
    cap = pref = profit = gp_cum = ZERO  # unreturned capital, unpaid pref, cumulative profit paid, GP cumulative
    res = Result()
    last = events[0][0] if events else None
    for on, kind, e in events:
        pref += _accrue((on - last).days, cap + pref, terms.hurdle)
        last = on
        if kind == 0:
            cap += e.amount
            continue
        t = Tiers()
        rem = e.amount
        x = min(rem, cap); t.to_lp_capital = x; cap -= x; rem -= x
        x = min(rem, pref); t.to_lp_pref = x; pref -= x; profit += x; rem -= x
        if rem and terms.catchup:
            need = terms.carry * profit - gp_cum  # dollars of catch-up that bring the GP to carry x profit
            x = min(rem, max(ZERO, need / (terms.catchup - terms.carry)))
            t.to_gp_catchup = x * terms.catchup
            t.to_lp_catchup = x - t.to_gp_catchup
            profit += x; gp_cum += t.to_gp_catchup; rem -= x
        if rem:
            t.to_gp_split = rem * terms.carry
            t.to_lp_split = rem - t.to_gp_split
            profit += rem; gp_cum += t.to_gp_split
        _to_cent(t, e.amount)
        res.steps.append(Step(on, e.amount, e.source, t))
        res.totals.add(t)
    return res


def _to_cent(t: Tiers, total: Decimal) -> None:
    for k in ("to_lp_capital", "to_lp_pref", "to_gp_catchup", "to_lp_catchup", "to_gp_split"):
        setattr(t, k, getattr(t, k).quantize(CENT, ROUND_HALF_UP))
    t.to_lp_split = total - (t.to_lp_capital + t.to_lp_pref + t.to_gp_catchup + t.to_lp_catchup + t.to_gp_split)


def per_lp(totals: Tiers, commitments: dict[str, Decimal]) -> dict[str, Decimal]:
    """Each LP's share of its LP-side proceeds, pro rata to commitment, rounding to the largest commitment."""
    if not commitments or any(c <= 0 for c in commitments.values()):
        raise ValueError("every LP needs a positive commitment")
    whole = sum(commitments.values())
    lp_total = totals.lp()
    out = {k: (lp_total * c / whole).quantize(CENT, ROUND_HALF_UP) for k, c in commitments.items()}
    gap = lp_total - sum(out.values())
    if gap:
        out[max(commitments, key=commitments.get)] += gap
    return out


def american(deals: dict[str, tuple[list[Flow], list[Flow]]], terms: Terms) -> dict[str, Result]:
    """Deal by deal: each deal's contributions and proceeds run through the tiers on their own."""
    return {name: run(c, d, terms) for name, (c, d) in deals.items()}


@dataclass(frozen=True)
class Escrow:
    pct: Decimal  # share of each deal distribution held back, e.g. 0.10
    days: int  # days the holdback waits before release
    source: str  # the LPA clause that sets the holdback


def hold_back(dists: list[Flow], escrow: Escrow) -> tuple[list[Flow], list[Flow]]:
    """Splits each distribution into the part paid now and the holdback released after `days`. The holdback
    runs through the tiers on its release date, as a distribution of its own."""
    if not (0 <= escrow.pct < 1) or escrow.days < 0:
        raise ValueError("escrow share must be below 1 and days not negative")
    now: list[Flow] = []
    later: list[Flow] = []
    for d in dists:
        held = (d.amount * escrow.pct).quantize(CENT, ROUND_HALF_UP)
        now.append(Flow(d.on, d.amount - held, d.source))
        if held:
            later.append(Flow(d.on + timedelta(days=escrow.days), held, f"{d.source}; escrow ({escrow.source})"))
    return now, later


@dataclass
class Clawback:
    gp_received: Decimal  # carry paid to the GP across all deals
    target: Decimal  # carry the GP is owed on the whole fund's profit
    amount: Decimal  # excess the GP returns to LPs; carry tax is not modelled


def clawback(contributions: list[Flow], distributions: list[Flow], results: dict[str, Result],
             terms: Terms) -> Clawback:
    """Deal-by-deal carry can overshoot the carry owed on the fund's total profit. The excess is clawed back.
    Assumes the catch-up is complete at fund level, which holds once the fund profit exceeds the pref."""
    received = sum((r.totals.gp() for r in results.values()), ZERO)
    profit = sum((d.amount for d in distributions), ZERO) - sum((c.amount for c in contributions), ZERO)
    owed = (terms.carry * profit).quantize(CENT, ROUND_HALF_UP) if profit > 0 else ZERO
    return Clawback(received, owed, max(ZERO, received - owed))
