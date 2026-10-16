"""Agent tools over the free/open data providers. Read-only; every result row carries its source URL.

Network access goes through the module-level `fetch(url) -> bytes`, so tests replace one function. Bulk sources that are
too large to pull per call (13F quarter zip about 100 MB, ADV roster zip) are read from a local path named in
PE_13F_ZIP / PE_ADV_ZIP; the tool says so when unset instead of guessing.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from app import (
    adv,
    dealscan,
    form13f,
    formd,
    fred,
    gleif,
    newsfeed,
    sanctions,
    secfeed,
    wikidata,
)
from app.agent import Ctx, ToolError, register_tool


def fetch(url: str) -> bytes:
    host = url.split("/")[2]
    return (secfeed.default_fetch(url) if host.endswith("sec.gov") else gleif.default_fetch(url))


def _plain(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o


def _rows(items, limit: int) -> list[dict]:
    return [_plain(asdict(i)) for i in list(items)[: max(1, min(int(limit), 50))]]


@register_tool("open_funding_rounds", "Private placements (SEC Form D) for an issuer name in a quarter. Self-reported amounts; None = Indefinite.",
               {"issuer": "text", "year": "int", "quarter": "int 1-4", "limit?": "int, default 10"})
def _rounds(ctx: Ctx, issuer: str, year: int, quarter: int, limit: int = 10):
    if int(quarter) not in (1, 2, 3, 4):
        raise ToolError("quarter must be 1-4")
    return _rows(formd.search(formd.rounds(int(year), int(quarter), fetch), issuer), limit)


@register_tool("open_entity_lookup", "Identify a company: GLEIF LEI records and Wikidata candidates, each with a source URL.",
               {"name": "text"})
def _entity(ctx: Ctx, name: str):
    return {"gleif": _rows(gleif.search(name, 5, fetch), 5), "wikidata": _rows(wikidata.search(name, 5, fetch), 5)}


@register_tool("open_macro_series", "Latest FRED observation for a series id (e.g. DGS10), with source URL.", {"series_id": "text"})
def _macro(ctx: Ctx, series_id: str):
    d, v, url = fred.latest(series_id, fetch)
    return {"series": series_id, "date": d, "value": str(v), "source": url}


@register_tool("open_deal_leads", "8-K filings mentioning a merger agreement in a date range (leads only; read terms from the filing).",
               {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "phrase?": "text", "limit?": "int, default 10"})
def _leads(ctx: Ctx, since: str, until: str, phrase: str = "agreement and plan of merger", limit: int = 10):
    return _rows(dealscan.scan(since, until, phrase, fetch=fetch), limit)


@register_tool("open_news", "Headlines from a news RSS feed (bbc_business, prnewswire_financial), optional text filter; links only.",
               {"feed": "text", "query?": "text", "limit?": "int, default 10"})
def _news(ctx: Ctx, feed: str, query: str | None = None, limit: int = 10):
    try:
        return _rows(newsfeed.headlines(feed, query, fetch=newsfeed.default_fetch), limit)
    except KeyError as e:
        raise ToolError(str(e)) from None


@register_tool("open_sanctions_screen", "Screen a name against an OpenSanctions list (default us_ofac_sdn). A miss is NOT a clearance. Non-commercial data licence.",
               {"name": "text", "dataset?": "text, default us_ofac_sdn"})
def _sanctions(ctx: Ctx, name: str, dataset: str = "us_ofac_sdn"):
    if not dataset.replace("_", "").isalnum():
        raise ToolError("bad dataset id")
    ms = sanctions.screen(sanctions.load(dataset, sanctions.default_fetch), name)
    return {"dataset": dataset, "matches": [{**_plain(asdict(m.entry)), "matched_on": m.matched_on, "how": m.how}
                                            for m in ms[:25]],
            "note": "screening aid only; confirm identity before relying on a miss or a hit"}


def _path(var: str) -> str:
    p = os.environ.get(var)
    if not p or not os.path.exists(p):
        raise ToolError(f"set {var} to the downloaded SEC zip path first")
    return p


@register_tool("open_13f_holdings", "Top 13F holdings of a manager (name match) from the local quarter zip in PE_13F_ZIP.",
               {"manager": "text", "limit?": "int, default 10"})
def _13f(ctx: Ctx, manager: str, limit: int = 10):
    zp = _path("PE_13F_ZIP")
    ms = form13f.find_managers(form13f.managers_from_zip(zp), manager)
    if not ms:
        return []
    return {"manager": _plain(asdict(ms[0])),
            "holdings": _rows(form13f.top(form13f.holdings_from_zip(zp, ms[0]), 50), limit)}


@register_tool("open_adviser_search", "Registered/exempt investment advisers by name from the local SEC roster zip in PE_ADV_ZIP (PE fund counts, private-fund assets).",
               {"name": "text", "limit?": "int, default 10"})
def _adv(ctx: Ctx, name: str, limit: int = 10):
    return _rows(adv.search(adv.parse_zip(_path("PE_ADV_ZIP")), name), limit)
