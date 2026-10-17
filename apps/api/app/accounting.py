"""Portfolio-company trial balance → monthly KPIs (revenue and net income), read from the workbook the accounting
connector stores. Template: sheet 'Monthly' has headers in row 1 'Period', 'Revenue (USD)', 'Net income (USD)';
each later row is one month. Each fact is cited to its cell, and the quote is the cell text as the ingest stored it,
so the citation check passes. A sheet that does not match the template gives nothing."""
from __future__ import annotations

import re

from app.fundadmin import Found, _cells

MONTHLY = "Monthly"
_COLUMNS = (("Revenue (USD)", "revenue_usd"), ("Net income (USD)", "net_income_usd"))
_PERIOD = re.compile(r"\d{4}-\d{2}")
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def extract(pages: list[tuple[int, str]]) -> list[Found]:
    cells = _cells(pages)
    headers = {c: raw for (s, c, r), (raw, _, _) in cells.items() if s == MONTHLY and r == 1}
    out: list[Found] = []
    period_cols = [c for c, h in headers.items() if h == "Period"]
    if not period_cols:
        return out
    rows = sorted({r for (s, c, r) in cells if s == MONTHLY and r > 1})
    for r in rows:
        period = cells.get((MONTHLY, period_cols[0], r))
        if period is None or not _PERIOD.fullmatch(period[0]):
            continue  # no month in the row: leave it for a person, do not guess
        for col_name, metric in _COLUMNS:
            cols = [c for c, h in headers.items() if h == col_name]
            cell = cells.get((MONTHLY, cols[0], r)) if cols else None
            if cell is None or not _NUMBER.fullmatch(cell[0].replace(",", "")):
                continue
            raw, page, quote = cell
            out.append(Found(metric, period[0], raw.replace(",", ""), page, quote))
    return out
