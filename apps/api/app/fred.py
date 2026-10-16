"""FRED series via the public CSV endpoint (no key): rates and macro for comps/valuation context.

FRED marks missing observations with "."; those are skipped, never filled. Series terms vary, check before redistributing.
"""
from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal

Fetch = Callable[[str], bytes]


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pe-ai/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def series_url(series_id: str, since: str | None = None) -> str:
    q = {"id": series_id, **({"cosd": since} if since else {})}
    return "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode(q)


def parse(text: str) -> list[tuple[str, Decimal]]:
    rows = list(csv.reader(io.StringIO(text)))[1:]
    return [(d, Decimal(v)) for d, v in rows if v.strip() not in ("", ".")]


def observations(series_id: str, since: str | None = None, fetch: Fetch = default_fetch) -> list[tuple[str, Decimal]]:
    return parse(fetch(series_url(series_id, since)).decode("utf-8", "replace"))


def latest(series_id: str, fetch: Fetch = default_fetch) -> tuple[str, Decimal, str]:
    """(date, value, citation url) of the newest non-missing observation."""
    obs = observations(series_id, fetch=fetch)
    if not obs:
        raise LookupError(f"fred: no observations for {series_id}")
    return obs[-1][0], obs[-1][1], f"https://fred.stlouisfed.org/series/{series_id}"
