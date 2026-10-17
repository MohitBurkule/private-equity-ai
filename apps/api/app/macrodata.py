"""Macro rates and FX for LBO and benchmarking: ECB euro reference rates (free, no key) and FRED series
(free key, FRED_API_KEY). Both implement `marketdata.Provider`, so each value is a Quote carrying its own
source name and as-of date. Nothing is filled in for a missing observation: a gap raises NoData.

Test fixtures: the ECB snapshot is a real saved response (tests/fixtures/macro); the FRED fixture is SYNTHETIC
because no key was available to the build. Re-save the FRED fixture from a real call before trusting it."""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from app.marketdata import NoData, Quote
from app.marketfeeds import Fetch, default_fetch

ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A?lastNObservations=5"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations?"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?"  # public download, no key


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
    """FRED series, e.g. 'DGS10' (10-year Treasury, percent) or 'SOFR'. Newest non-missing observation. FRED
    reports missing days as '.', which is skipped, not treated as zero. Currency is the unit the caller names.
    With an api_key the JSON API is used; without one, the public CSV download is used (no key needed)."""
    name = "fred"

    def __init__(self, api_key: str = "", unit: str = "PCT", fetch: Fetch = default_fetch):
        self._key, self.unit, self._fetch = api_key, unit, fetch

    def quote(self, series: str) -> Quote:
        sid = series.upper()
        if self._key:
            q = urllib.parse.urlencode({"series_id": sid, "api_key": self._key, "file_type": "json",
                                        "sort_order": "desc", "limit": 10})
            doc = json.loads(self._fetch(FRED_URL + q, {}))
            rows = [(o.get("date"), o.get("value")) for o in doc.get("observations", [])]
        else:
            raw = self._fetch(FRED_CSV_URL + urllib.parse.urlencode({"id": sid}), {})
            reader = csv.reader(io.StringIO(raw.decode("utf-8", "replace")))
            next(reader, None)  # header: observation_date,<ID>
            rows = [(r[0], r[1]) for r in reader if len(r) == 2]
        for day, value in sorted(rows, reverse=True):
            if value not in (None, "", "."):
                return Quote(sid, _dec(value, f"fred {sid}"), self.unit, day, self.name)
        raise NoData(f"fred: no recent observation for {sid}")


def registered(fetch: Fetch = default_fetch) -> list:
    """ECB and FRED are both listed. FRED uses the key when FRED_API_KEY is set, else the public CSV."""
    return [EcbFxProvider(fetch), FredProvider(os.environ.get("FRED_API_KEY", ""), fetch=fetch)]


def fx_rate(provider: EcbFxProvider, frm: str, to: str) -> tuple[Decimal, str, str]:
    """Units of `to` per one unit of `frm`, from ECB euro reference rates. Cross rates go through EUR; the
    as-of date is the older of the two days used. Returns (rate, as_of, source)."""
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return Decimal(1), "", "identity"
    if to == "EUR":
        q = provider.quote(frm)
        return q.price, q.as_of, provider.name
    if frm == "EUR":
        q = provider.quote(to)
        return 1 / q.price, q.as_of, provider.name
    a, b = provider.quote(frm), provider.quote(to)
    return a.price / b.price, min(a.as_of, b.as_of), provider.name


def rate_with_margin(provider: FredProvider, series: str, margin_pct: str) -> tuple[Decimal, dict]:
    """A floating base rate plus a margin, both in percent. The citation names the series, its date and value."""
    q = provider.quote(series)
    margin = _dec(str(margin_pct), "margin")
    src = {"macro": True, "series": q.symbol, "as_of": q.as_of, "base_value": str(q.price),
           "source": q.source, "quote": f"{q.symbol} {q.as_of} = {q.price}%"}
    return q.price + margin, src
