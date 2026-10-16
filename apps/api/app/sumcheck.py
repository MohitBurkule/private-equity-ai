"""Do printed parts add up to a printed total? Reports the difference; never rounds a gap away.

Used for share counts, cap tables and sums of segments. A gap is a finding (a typo in the filing,
a double count, a missing line), so it is returned with the exact amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SumCheck:
    status: str  # ties | gap | rounding
    computed: Decimal
    stated: Decimal
    difference: Decimal  # stated - computed
    detail: str = ""


def sum_check(parts: list[Decimal], stated: Decimal, rounding_unit: Decimal = Decimal(0)) -> SumCheck:
    """`rounding_unit` > 0 allows a gap of up to that many units per printed part (tables rounded to
    thousands can be off by 1 per part); a gap inside that allowance is labelled rounding, not ties."""
    computed = sum(parts, Decimal(0))
    diff = stated - computed
    if diff == 0:
        return SumCheck("ties", computed, stated, diff)
    if rounding_unit > 0 and abs(diff) <= rounding_unit * len(parts):
        return SumCheck("rounding", computed, stated, diff, "within rounding of the printed parts")
    return SumCheck("gap", computed, stated, diff, "parts do not add up to the stated total")
