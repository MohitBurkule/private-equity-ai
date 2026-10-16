"""Exit waterfall for a preferred-stock cap table. Pure code; the terms are the caller's inputs.

Per class: shares, amount invested, liquidation-preference multiple, seniority rank (1 is paid first;
equal ranks share pro rata to their preference), participating or not, and an optional cap on total
proceeds as a multiple of the amount invested (participating classes only). A class converts to common
when that pays more than staying preferred; conversion decisions are found by iterating until stable.
Payouts always add up to the exit value. Terms the model does not cover (dividends, anti-dilution
adjustments, management carve-outs, option exercise prices) are NOT applied: read them from the charter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class PrefClass:
    name: str
    shares: Decimal
    invested: Decimal
    pref_multiple: Decimal = Decimal(1)
    rank: int = 1
    participating: bool = False
    cap_multiple: Decimal | None = None  # participating only: total proceeds <= cap_multiple * invested


@dataclass
class Result:
    exit_value: Decimal
    payouts: dict[str, Decimal]
    converted: list[str]
    status: str  # ok | not_converged
    detail: str = ""


def _distribute(exit_value: Decimal, classes: list[PrefClass], common: Decimal, conv: set[str]) -> dict[str, Decimal]:
    pay = {c.name: Decimal(0) for c in classes}
    pay["common"] = Decimal(0)
    left = exit_value
    stay = [c for c in classes if c.name not in conv]
    for rank in sorted({c.rank for c in stay}):
        tier = [c for c in stay if c.rank == rank]
        owed = {c.name: c.invested * c.pref_multiple for c in tier}
        total = sum(owed.values(), Decimal(0))
        paid = min(left, total)
        for c in tier:
            pay[c.name] += paid * owed[c.name] / total if total else Decimal(0)
        left -= paid
    # residual: common, converted classes and participating classes share by shares; caps bind iteratively
    sharers = {"common": common}
    sharers.update({c.name: c.shares for c in classes if c.name in conv})
    sharers.update({c.name: c.shares for c in stay if c.participating})
    caps = {c.name: c.cap_multiple * c.invested for c in stay if c.participating and c.cap_multiple is not None}
    while left > 0 and sharers:
        total_sh = sum(sharers.values(), Decimal(0))
        if total_sh == 0:
            break
        share = {n: left * s / total_sh for n, s in sharers.items()}
        capped = [n for n in share if n in caps and pay[n] + share[n] > caps[n]]
        if not capped:
            for n, v in share.items():
                pay[n] += v
            left = Decimal(0)
            break
        for n in capped:
            give = caps[n] - pay[n]
            pay[n] += give
            left -= give
            del sharers[n]
    if left > 0:
        pay["common"] += left  # nobody else can take it (everyone capped): goes to common
    return pay


def waterfall(exit_value: Decimal, classes: list[PrefClass], common_shares: Decimal) -> Result:
    if exit_value < 0 or common_shares < 0 or any(c.shares < 0 or c.invested < 0 for c in classes):
        raise ValueError("negative amounts are not allowed")
    if len({c.name for c in classes}) != len(classes) or any(c.name == "common" for c in classes):
        raise ValueError("class names must be unique and not 'common'")
    conv: set[str] = set()
    cent = Decimal("0.01")
    for _ in range(len(classes) * 2 + 2):
        pay = _distribute(exit_value, classes, common_shares, conv)
        gains = {c.name: _distribute(exit_value, classes, common_shares, conv ^ {c.name})[c.name] - pay[c.name]
                 for c in classes}
        best = max(gains, key=lambda n: gains[n], default=None)
        if best is None or gains[best] <= 0:
            return Result(exit_value, _to_cents(pay, exit_value, cent), sorted(conv), "ok")
        conv ^= {best}  # the class with the biggest gain from switching switches; then re-evaluate everyone
    return Result(exit_value, _to_cents(pay, exit_value, cent), sorted(conv), "not_converged",
                  "conversion choices kept changing; check terms")


def _to_cents(pay: dict[str, Decimal], exit_value: Decimal, cent: Decimal) -> dict[str, Decimal]:
    out = {k: v.quantize(cent) for k, v in pay.items()}
    diff = exit_value - sum(out.values(), Decimal(0))
    if diff:  # rounding remainder (a few cents at most) goes to the largest recipient
        top = max(out, key=lambda k: out[k])
        out[top] += diff
    return out
