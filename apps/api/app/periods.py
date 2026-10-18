"""Period labels: which ones we recognise. Advisory only. A fact with an unrecognised period is still stored, and the
writer gets a warning back, because some real labels ("per agreement") are not periods at all and must not be refused.

Known: a calendar year (2026), a fiscal year (FY24, FY2024), a year and month (2026-09), a year-end date
(2026-06-30), a quarter (2026-Q2, 2026Q2, FY2026Q2, Q1 with no year is NOT known), and the trailing or forward
twelve months (LTM, NTM)."""
from __future__ import annotations

import re

_KNOWN = (
    re.compile(r"^\d{4}$"),
    re.compile(r"^FY\d{2}$"),
    re.compile(r"^FY\d{4}$"),
    re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-?Q[1-4]$"),
    re.compile(r"^FY\d{4}Q[1-4]$"),
    re.compile(r"^(LTM|NTM)$"),
)


def period_warning(period: str) -> str | None:
    """None when the label is a known period, else a one-line warning naming it."""
    p = period.strip()
    if any(rx.match(p) for rx in _KNOWN):
        return None
    return f"period {period!r} is not a recognised label; stored as written"
