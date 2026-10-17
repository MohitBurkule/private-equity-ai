"""Macro rates and FX for LBO and benchmarking: ECB euro reference rates (free, no key) and FRED series
(free key, FRED_API_KEY). Both implement `marketdata.Provider`, so each value is a Quote carrying its own
source name and as-of date. Nothing is filled in for a missing observation: a gap raises NoData.

Test fixtures: the ECB snapshot is a real saved response (tests/fixtures/macro); the FRED fixture is SYNTHETIC
because no key was available to the build. Re-save the FRED fixture from a real call before trusting it."""
from __future__ import annotations

import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from app.marketdata import NoData, Quote
from app.marketfeeds import Fetch, default_fetch

ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A?lastNObservations=5"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations?"


def _dec(v: str, what: str) -> Decimal:
    try:
        d = Decimal(v)
    except (InvalidOperation, TypeError):
        raise NoData(f"{what}: unreadable value {v!r}") from None
    if not d.is_finite():
        raise NoData(f"{what}: non-finite value {v!r}")
    return d


class EcbFxProvider:
    """ECB euro reference rate: symbol 'USD' gives EUR per 1 USD, as of the newest published day."""
    name = "ecb"

    def __init__(self, fetch: Fetch = default_fetch):
        self._fetch = fetch

    def quote(self, symbol: str) -> Quote:
        ccy = symbol.upper()
        raw = self._fetch(ECB_URL.format(ccy=ccy), {"Accept": "application/vnd.sdmx.data+xml"})
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise NoData(f"ecb: unreadable answer for {ccy}") from e
        obs = [(o.find(".//{*}ObsDimension"), o.find(".//{*}ObsValue")) for o in root.iter() if o.tag.endswith("}Obs")]
        pairs = [(d.get("value"), v.get("value")) for d, v in obs if d is not None and v is not None]
        if not pairs:
            raise NoData(f"ecb: no observations for {ccy}")
        day, value = max(pairs)  # ISO dates sort as text
        return Quote(f"{ccy}/EUR", _dec(value, f"ecb {ccy}"), "EUR", day, self.name)


class FredProvider:
    """FRED series, e.g. 'DGS10' (10-year Treasury, percent). Newest non-missing observation. FRED reports
    missing days as '.', which is skipped, not treated as zero. Currency is the unit the caller names."""
    name = "fred"

    def __init__(self, api_key: str, unit: str = "PCT", fetch: Fetch = default_fetch):
        if not api_key:
            raise NoData("fred: FRED_API_KEY is required")
        self._key, self.unit, self._fetch = api_key, unit, fetch

    def quote(self, series: str) -> Quote:
        q = urllib.parse.urlencode({"series_id": series.upper(), "api_key": self._key, "file_type": "json",
                                    "sort_order": "desc", "limit": 10})
        doc = json.loads(self._fetch(FRED_URL + q, {}))
        for o in doc.get("observations", []):
            if o.get("value") not in (None, "", "."):
                return Quote(series.upper(), _dec(o["value"], f"fred {series}"), self.unit, o["date"], self.name)
        raise NoData(f"fred: no recent observation for {series}")


def registered(fetch: Fetch = default_fetch) -> list:
    """ECB is always listed. FRED is listed only when FRED_API_KEY is set."""
    out: list = [EcbFxProvider(fetch)]
    if os.environ.get("FRED_API_KEY"):
        out.append(FredProvider(os.environ["FRED_API_KEY"], fetch=fetch))
    return out
