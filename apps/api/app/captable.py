"""Cap table → cited share and ownership facts, read from the workbook the Carta connector stores. Template: sheet
'Cap Table' has headers in row 1 'Holder', 'Share class', 'Shares', 'Ownership (%)', 'As of'; each later row is one
holding. The holder is the entity, the as-of date the period. Each fact is cited to its cell. A row with a
non-numeric or out-of-range figure gives nothing, so a bad cell is never stored as a number."""
from __future__ import annotations

import re

from app.fundadmin import Found, _cells

SHEET = "Cap Table"
_NUMBER = re.compile(r"\d+(\.\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def extract(pages: list[tuple[int, str]]) -> list[Found]:
    cells = _cells(pages)
    headers = {c: raw for (s, c, r), (raw, _, _) in cells.items() if s == SHEET and r == 1}
    col = {name: [c for c, h in headers.items() if h == name] for name in
           ("Holder", "Share class", "Shares", "Ownership (%)", "As of")}
    if not all(col.values()):
        return []
    rows = sorted({r for (s, c, r) in cells if s == SHEET and r > 1})
    out: list[Found] = []
    for r in rows:
        holder, cls, shares, pct, as_of = (cells.get((SHEET, col[n][0], r))
                                           for n in ("Holder", "Share class", "Shares", "Ownership (%)", "As of"))
        if None in (holder, cls, shares, as_of) or not _DATE.fullmatch(as_of[0]):
            continue
        if not _NUMBER.fullmatch(shares[0].replace(",", "")) or not holder[0].strip() or not cls[0].strip():
            continue
        out.append(Found(f"shares {cls[0]}", as_of[0], shares[0].replace(",", ""), shares[1], shares[2], holder[0]))
        if pct is not None and _NUMBER.fullmatch(pct[0]) and float(pct[0]) <= 100:
            out.append(Found(f"ownership_pct {cls[0]}", as_of[0], pct[0], pct[1], pct[2], holder[0]))
    return out
