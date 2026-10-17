"""Live market-data providers for the `marketdata.Provider` interface.

Free: Stooq (CSV), Yahoo chart JSON. Keyed: FactSet Prices (FACTSET_USERNAME_SERIAL + FACTSET_API_KEY).
Every provider takes an injectable `fetch(url, headers) -> bytes`, returns a Quote with the source's own
as-of date, and raises NoData when the source has nothing; a missing field is NoData, never a default.

The test fixtures are SYNTHETIC, shaped from each vendor's published response format; the sandbox that
built this could not reach any of these hosts. Replace them with saved real responses and re-run the
tests before trusting a provider with real money.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.marketdata import NoData, Quote

Fetch = Callable[[str, dict[str, str]], bytes]


def default_fetch(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1", **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _dec(v) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise NoData(f"unreadable price {v!r}") from None
    if not d.is_finite() or d < 0:
        raise NoData(f"unusable price {v!r}")
    return d


class StooqProvider:
    """https://stooq.com CSV quotes. Symbols look like 'aapl.us'; currency is not in the file, so the
    caller must say it (`currency`), and no guess is made."""
    name = "stooq"

    def __init__(self, currency: str, fetch: Fetch = default_fetch):
        self.currency, self._fetch = currency.upper(), fetch

    def quote(self, symbol: str) -> Quote:
        url = "https://stooq.com/q/l/?" + urllib.parse.urlencode({"s": symbol.lower(), "f": "sd2c", "h": "", "e": "csv"})
        rows = list(csv.DictReader(io.StringIO(self._fetch(url, {}).decode("utf-8", "replace"))))
        if not rows:
            raise NoData(f"stooq: empty answer for {symbol}")
        r = {k.strip().lower(): (v or "").strip() for k, v in rows[0].items() if k}
        if r.get("close", "N/D") in ("N/D", "") or r.get("date", "N/D") in ("N/D", ""):
            raise NoData(f"stooq: no data for {symbol}")
        return Quote(symbol.upper(), _dec(r["close"]), self.currency, r["date"], self.name)


class YahooProvider:
    """Yahoo chart endpoint (unofficial, can change or be blocked without notice)."""
    name = "yahoo"

    def __init__(self, fetch: Fetch = default_fetch):
        self._fetch = fetch

    def quote(self, symbol: str) -> Quote:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol)
        doc = json.loads(self._fetch(url, {}))
        res = ((doc.get("chart") or {}).get("result") or [None])[0]
        if not res:
            raise NoData(f"yahoo: no result for {symbol}")
        m = res.get("meta") or {}
        if m.get("regularMarketPrice") is None or not m.get("currency") or not m.get("regularMarketTime"):
            raise NoData(f"yahoo: incomplete answer for {symbol}")
        day = datetime.fromtimestamp(int(m["regularMarketTime"]), UTC).date().isoformat()
        return Quote(symbol.upper(), _dec(m["regularMarketPrice"]), str(m["currency"]).upper(), day, self.name)


class FactSetProvider:
    """FactSet Prices API (/content/factset-prices/v1/prices). Needs a licence; credentials come from
    FACTSET_USERNAME_SERIAL and FACTSET_API_KEY. Ids are FactSet identifiers such as 'AAPL-US'."""
    name = "factset"
    BASE = "https://api.factset.com/content/factset-prices/v1/prices"

    def __init__(self, username_serial: str | None = None, api_key: str | None = None, fetch: Fetch = default_fetch):
        u = username_serial or os.environ.get("FACTSET_USERNAME_SERIAL")
        k = api_key or os.environ.get("FACTSET_API_KEY")
        if not u or not k:
            raise RuntimeError("FACTSET_USERNAME_SERIAL and FACTSET_API_KEY are required")
        self._auth = "Basic " + base64.b64encode(f"{u}:{k}".encode()).decode()
        self._fetch = fetch

    def quote(self, symbol: str) -> Quote:
        url = self.BASE + "?" + urllib.parse.urlencode({"ids": symbol, "frequency": "D", "adjust": "SPLIT"})
        doc = json.loads(self._fetch(url, {"Authorization": self._auth, "Accept": "application/json"}))
        rows = [r for r in doc.get("data", []) if r.get("price") is not None and r.get("date") and r.get("currency")]
        if not rows:
            raise NoData(f"factset: no price for {symbol}")
        last = max(rows, key=lambda r: r["date"])
        return Quote(symbol.upper(), _dec(last["price"]), str(last["currency"]).upper(), str(last["date"])[:10], self.name)


def from_env(fetch: Fetch = default_fetch) -> list:
    """Providers whose credentials are present. Free ones are always listed; Stooq needs a currency so
    is registered by the caller who knows it."""
    out = [YahooProvider(fetch)]
    if os.environ.get("FACTSET_USERNAME_SERIAL") and os.environ.get("FACTSET_API_KEY"):
        out.append(FactSetProvider(fetch=fetch))
    from app.marketvendors import (  # licensed; only when configured
        CapIQProvider,
        PitchBookProvider,
    )
    for cls in (CapIQProvider, PitchBookProvider):
        try:
            out.append(cls(fetch=fetch))
        except RuntimeError:
            pass
    return out
