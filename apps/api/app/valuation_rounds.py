"""Valuation and round history from a user's own export: company, round date, round type, post-money value, currency.

Same rules as holdings: no platform layout is assumed, nothing is defaulted, and a bad row is rejected with its
line and reason rather than repaired. Every accepted row keeps its source document and CSV line, so each
valuation can be traced back to the file it came from.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

REQUIRED = ("company", "round_date", "round_type", "post_money", "currency")


@dataclass
class RoundRow:
    line: int
    company: str
    round_date: str
    round_type: str
    post_money: Decimal
    currency: str


def parse_rounds(text: str) -> tuple[list[RoundRow], list[dict], list[str]]:
    """Return (rows, errors, missing). `missing` lists required columns that the header lacks."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return [], [], list(REQUIRED)
    cols = {h.strip().lower(): i for i, h in enumerate(header)}
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        return [], [], missing
    rows: list[RoundRow] = []
    errors: list[dict] = []
    for line, rec in enumerate(reader, 2):
        if not any(c.strip() for c in rec):
            continue

        def get(f, rec=rec):
            return rec[cols[f]].strip() if cols[f] < len(rec) else ""
        try:
            company = get("company")
            if not company:
                raise ValueError("company is empty")
            d = get("round_date")
            date.fromisoformat(d)  # refuses anything but a real ISO date
            value = Decimal(get("post_money").replace(",", ""))
            if not value.is_finite() or value <= 0:
                raise ValueError("post_money must be a positive number")
            cur = get("currency").upper()
            if not re.fullmatch(r"[A-Z]{3}", cur):
                raise ValueError("currency must be a 3-letter code")
        except (InvalidOperation, ValueError) as e:
            errors.append({"line": line, "reason": str(e) or "unreadable value"})
            continue
        rows.append(RoundRow(line, company, d, get("round_type"), value, cur))
    return rows, errors, []
