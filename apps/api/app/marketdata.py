"""Market-data adapter interface.

A provider returns Quote rows with a source label and an as-of date, or raises
NoData. Nothing is defaulted or guessed. Paid feeds (FactSet, PitchBook) plug in
by implementing `Provider`; the CSV provider is for data a user already holds.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol


class NoData(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    currency: str
    as_of: str  # ISO date as printed by the source
    source: str


class Provider(Protocol):
    name: str

    def quote(self, symbol: str) -> Quote: ...


class CsvProvider:
    """Quotes from a CSV with columns symbol,price,currency,as_of. Latest as_of wins per symbol."""

    def __init__(self, text: str, name: str = "csv"):
        self.name = name
        self._rows: dict[str, Quote] = {}
        reader = csv.DictReader(io.StringIO(text))
        need = {"symbol", "price", "currency", "as_of"}
        if not reader.fieldnames or not need <= {f.strip().lower() for f in reader.fieldnames}:
            raise ValueError(f"CSV needs columns {sorted(need)}")
        for i, raw in enumerate(reader, 2):
            r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            try:
                price = Decimal(r["price"].replace(",", ""))
            except InvalidOperation as e:
                raise ValueError(f"line {i}: bad price {r['price']!r}") from e
            if not r["symbol"] or not r["as_of"] or not r["currency"] or price < 0:
                raise ValueError(f"line {i}: incomplete or negative row")
            q = Quote(r["symbol"].upper(), price, r["currency"].upper(), r["as_of"], name)
            old = self._rows.get(q.symbol)
            if old is None or q.as_of >= old.as_of:
                self._rows[q.symbol] = q

    def quote(self, symbol: str) -> Quote:
        try:
            return self._rows[symbol.upper()]
        except KeyError:
            raise NoData(f"no quote for {symbol}") from None


REGISTRY: dict[str, Provider] = {}


def register(p: Provider) -> None:
    REGISTRY[p.name] = p


def get(name: str) -> Provider:
    try:
        return REGISTRY[name]
    except KeyError:
        raise NoData(f"unknown provider {name}; available: {sorted(REGISTRY)}") from None
