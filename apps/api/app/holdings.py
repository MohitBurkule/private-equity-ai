"""Import of a user's own secondary-market holdings export (Seedrs/Republic, Crowdcube or any CSV).

No platform scraping and no assumed platform layout: columns are found by common names or by a
mapping the caller supplies. Every accepted row keeps its source document and CSV line number.
Bad rows are rejected with a reason and never repaired. Prices are never defaulted, currencies
are never assumed, dates must be ISO (YYYY-MM-DD).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

ALIASES = {
    "company": ["company", "company_name", "business", "issuer", "startup", "name"],
    "shares": ["shares", "quantity", "units", "number_of_shares", "shares_held"],
    "price": ["price_per_share", "cost_per_share", "share_price", "price", "avg_price"],
    "currency": ["currency", "ccy"],
    "date": ["date", "acquired", "purchase_date", "acquired_on", "trade_date"],
}
_SYMBOL = re.compile(r"^[£$€]")


@dataclass
class HoldingRow:
    line: int
    company: str
    shares: Decimal
    price: Decimal
    currency: str
    acquired: str | None


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def _num(s: str) -> Decimal:
    s = _SYMBOL.sub("", s.strip()).replace(",", "")
    v = Decimal(s)
    if not v.is_finite():
        raise InvalidOperation
    return v


def parse_holdings(text: str, mapping: dict[str, str] | None = None, currency: str | None = None):
    """Return (rows, errors, missing). `missing` lists required fields with no column."""
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if not header:
        return [], [], list(ALIASES)
    cols = {_norm(h): i for i, h in enumerate(header)}
    idx: dict[str, int] = {}
    for field, names in ALIASES.items():
        want = [_norm(mapping[field])] if mapping and field in mapping else names
        for n in want:
            if n in cols:
                idx[field] = cols[n]
                break
    missing = [f for f in ("company", "shares", "price") if f not in idx]
    if "currency" not in idx and not currency:
        missing.append("currency")
    if missing:
        return [], [], missing
    rows: list[HoldingRow] = []
    errors: list[dict] = []
    for line, rec in enumerate(reader, 2):
        if not any(c.strip() for c in rec):
            continue
        def get(f, rec=rec):
            return rec[idx[f]].strip() if f in idx and idx[f] < len(rec) else ""
        try:
            company = get("company")
            if not company:
                raise ValueError("company is empty")
            shares, price = _num(get("shares")), _num(get("price"))
            if shares <= 0 or price < 0:
                raise ValueError("shares must be positive and price not negative")
            cur = (get("currency") or currency or "").upper()
            if not re.fullmatch(r"[A-Z]{3}", cur):
                raise ValueError("currency must be a 3-letter code")
            d = get("date") or None
            if d:
                date.fromisoformat(d)
        except (InvalidOperation, ValueError) as e:
            errors.append({"line": line, "reason": str(e) or "unreadable number"})
            continue
        rows.append(HoldingRow(line, company, shares, price, cur, d))
    return rows, errors, []
