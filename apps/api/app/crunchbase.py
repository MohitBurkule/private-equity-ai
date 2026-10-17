"""Crunchbase legacy bulk CSV reader (funding_rounds.csv) into typed rows.

Column names follow the public legacy bulk export sample. Docs:
https://data.crunchbase.com/v4-legacy/docs/legacy-csv-export.md (UTF-8, comma, double-quote escape).
This reads rows only; it does not create documents or facts. Use `vendorfacts` on ingested
documents for fact proposals.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

COLUMNS = {
    "company": "org_name",
    "round_type": "investment_type",
    "announced": "announced_on",
    "raised_usd": "raised_amount_usd",
    "post_money_usd": "post_money_valuation_usd",
    "investors": "investor_count",
}


@dataclass(frozen=True)
class FundingRound:
    company: str | None
    round_type: str | None
    announced: date | None
    raised_usd: Decimal | None
    post_money_usd: Decimal | None
    investors: int | None


def _blank(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _decimal(value: str | None) -> Decimal | None:
    text = _blank(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc


def _int(value: str | None) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise ValueError(f"not a whole number: {number}")
    return int(number)


def _date(value: str | None) -> date | None:
    text = _blank(value)
    return None if text is None else date.fromisoformat(text)


def read_funding_rounds_numbered(path: Path) -> list[tuple[int, FundingRound]]:
    """Each round with its data row number (1-based, header excluded), so a citation can name the row."""
    with open(path, encoding="utf-8", newline="") as handle:
        return [
            (n, FundingRound(
                company=_blank(row.get(COLUMNS["company"])),
                round_type=_blank(row.get(COLUMNS["round_type"])),
                announced=_date(row.get(COLUMNS["announced"])),
                raised_usd=_decimal(row.get(COLUMNS["raised_usd"])),
                post_money_usd=_decimal(row.get(COLUMNS["post_money_usd"])),
                investors=_int(row.get(COLUMNS["investors"])),
            ))
            for n, row in enumerate(csv.DictReader(handle), 1)
        ]


def read_funding_rounds(path: Path) -> list[FundingRound]:
    return [r for _, r in read_funding_rounds_numbered(path)]
