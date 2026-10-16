"""Place table-row values into columns when the text extraction dropped blank cells.

Some filings print a blank cell as nothing, so a row has fewer tokens than the table has columns and
positional reading puts values under the wrong period. Here each short row is tried in every
order-preserving placement and only placements where base + sum(rows) equals the printed total in
every column are kept. One surviving column vector is a resolved row; more than one, or too many
placements to try, is reported as ambiguous. Nothing is guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from math import comb

MAX_PLACEMENTS = 2_000_000


@dataclass
class TieOut:
    status: str  # resolved | ambiguous | no_solution | too_large
    rows: dict[str, list[Decimal]] | None = None  # label -> value per column, when resolved
    solutions: int = 0
    detail: str = ""


def _placements(tokens: list[Decimal | None], ncols: int) -> list[tuple[Decimal, ...]]:
    """Distinct numeric vectors from placing the tokens, in order, into ncols columns (None = printed dash)."""
    seen: set[tuple[Decimal, ...]] = set()
    for pos in combinations(range(ncols), len(tokens)):
        v = [Decimal(0)] * ncols
        for p, t in zip(pos, tokens, strict=True):
            v[p] = t or Decimal(0)
        seen.add(tuple(v))
    return sorted(seen)


def tie_out(rows: dict[str, list[Decimal | None]], base: list[Decimal], total: list[Decimal]) -> TieOut:
    n = len(base)
    if len(total) != n:
        return TieOut("no_solution", detail="base and total have different column counts")
    if any(len(t) > n for t in rows.values()):
        return TieOut("no_solution", detail="a row has more values than columns")
    size = 1
    for t in rows.values():
        size *= comb(n, len(t))
        if size > MAX_PLACEMENTS:
            return TieOut("too_large", detail=f"more than {MAX_PLACEMENTS} placements to try")
    labels = list(rows)
    options = [_placements(rows[k], n) for k in labels]
    need = tuple(t - b for b, t in zip(base, total, strict=True))
    # sequential search over rows, keeping the set of reachable column-sum vectors with one witness each
    reach: dict[tuple[Decimal, ...], list[tuple[Decimal, ...]]] = {tuple([Decimal(0)] * n): []}
    for opts in options:
        nxt: dict[tuple[Decimal, ...], list[tuple[Decimal, ...]]] = {}
        for acc, chosen in reach.items():
            for o in opts:
                s = tuple(a + b for a, b in zip(acc, o, strict=True))
                nxt.setdefault(s, chosen + [o])
        reach = nxt
    if need not in reach:
        return TieOut("no_solution", detail="no placement makes the columns add up to the printed total")
    # count distinct full solutions (bounded by the same cap) to tell resolved from ambiguous
    count = _count(options, need, n)
    if count == 1:
        return TieOut("resolved", {k: list(v) for k, v in zip(labels, reach[need], strict=True)}, 1)
    return TieOut("ambiguous", solutions=count, detail="more than one placement ties out")


def _count(options: list[list[tuple[Decimal, ...]]], need: tuple[Decimal, ...], n: int) -> int:
    counts: dict[tuple[Decimal, ...], int] = {tuple([Decimal(0)] * n): 1}
    for opts in options:
        nxt: dict[tuple[Decimal, ...], int] = {}
        for acc, c in counts.items():
            for o in opts:
                s = tuple(a + b for a, b in zip(acc, o, strict=True))
                nxt[s] = nxt.get(s, 0) + c
        counts = nxt
    return counts.get(need, 0)
