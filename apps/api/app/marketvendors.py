"""Capital IQ and PitchBook price adapters behind the same `Provider` interface as FactSet.

Both are licensed products. Base URLs and tokens come from the environment, and nothing is hard-coded,
because the endpoint paths and response shapes must be checked against the customer's own licence docs.
The response parsing below assumes this shape, which is NOT verified against either vendor:
    {"data": [{"id": str, "price": number, "currency": str, "date": "YYYY-MM-DD"}]}
Until it is checked, treat these adapters as untested against live data. Fixtures in tests are SYNTHETIC.
Unreadable or missing fields raise NoData; nothing is guessed."""
from __future__ import annotations

import json
import os
import urllib.parse

from app.marketdata import NoData, Quote
from app.marketfeeds import Fetch, _dec, default_fetch


def _from_rows(doc: dict, symbol: str, source: str) -> Quote:
    rows = [r for r in (doc.get("data") or []) if r.get("price") is not None and r.get("currency") and r.get("date")]
    if not rows:
        raise NoData(f"{source}: no price for {symbol}")
    last = max(rows, key=lambda r: str(r["date"]))
    return Quote(symbol.upper(), _dec(last["price"]), str(last["currency"]).upper(), str(last["date"])[:10], source)


class _EnvVendor:
    name = ""
    base_env = ""
    token_env = ""

    def __init__(self, base_url: str | None = None, token: str | None = None, fetch: Fetch = default_fetch):
        self.base = (base_url or os.environ.get(self.base_env) or "").rstrip("/")
        tok = token or os.environ.get(self.token_env)
        if not self.base or not tok:
            raise RuntimeError(f"{self.base_env} and {self.token_env} are required for {self.name}")
        if not self.base.startswith("https://"):
            raise RuntimeError(f"{self.base_env} must be https")
        self._auth = f"Bearer {tok}"
        self._fetch = fetch

    def quote(self, symbol: str) -> Quote:
        url = f"{self.base}/prices?" + urllib.parse.urlencode({"ids": symbol, "frequency": "daily"})
        doc = json.loads(self._fetch(url, {"Authorization": self._auth, "Accept": "application/json"}))
        return _from_rows(doc, symbol, self.name)


class CapIQProvider(_EnvVendor):
    name = "capiq"
    base_env = "CAPIQ_BASE_URL"
    token_env = "CAPIQ_TOKEN"


class PitchBookProvider(_EnvVendor):
    name = "pitchbook"
    base_env = "PITCHBOOK_BASE_URL"
    token_env = "PITCHBOOK_TOKEN"
