""""Have we seen this?" lookup across the firm's own records: targets, portfolio companies and deals.

Names are normalised (case, punctuation, legal suffixes such as Inc, Ltd, plc) before comparing, so
"Acme Holdings, Inc." matches "ACME HOLDINGS". Matches are exact after normalising, or one name contains
the other when the shorter one has at least MIN_CONTAIN characters. Each hit says which rule matched.
A bare SIC code (four or five digits) also matches the deals and portfolio companies filed under it, so
"have we seen this sector" works without a name. Nothing is merged or assumed to be the same company: the caller decides.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Deal, Target
from app.portfolio import PortfolioCompany

MIN_CONTAIN = 5
_SUFFIX = re.compile(r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|lp|llp|gmbh|sa|holdings|group)\b")


def normalise(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match(q: str, name: str) -> str | None:
    n = normalise(name)
    if not q or not n:
        return None
    if q == n:
        return "exact"
    short, long_ = (q, n) if len(q) <= len(n) else (n, q)
    if len(short) >= MIN_CONTAIN and f" {short} " in f" {long_} ":
        return "contains"
    return None


_SIC = re.compile(r"\d{4,5}")


def _deal_rule(d: Deal, q: str, raw: str, sic: str | None) -> str | None:
    """Registry identifiers match exactly and outrank names. Aliases match like the deal name does."""
    if (d.cik and raw.lstrip("0") == d.cik) or (d.lei and raw.upper() == d.lei):
        return "cik" if raw.isdigit() else "lei"
    rule = _match(q, d.name)
    if rule:
        return rule
    for alias in (a.strip() for a in (d.aliases or "").split(",")):
        if alias and _match(q, alias):
            return "alias"
    return "sic" if sic and d.sic == sic else None


def lookup(db: Session, tenant: str, query: str, deal_scope: set[str] | None = None) -> dict:
    q = normalise(query)
    sic = query.strip() if _SIC.fullmatch(query.strip()) else None
    hits: list[dict] = []
    for t in db.query(Target).filter_by(tenant_id=tenant):
        rule = _match(q, t.name)
        if rule:
            hits.append({"kind": "target", "id": t.id, "name": t.name, "rule": rule, "status": t.status,
                         "source": t.source, "source_url": t.source_url})
    for c in db.query(PortfolioCompany).filter_by(tenant_id=tenant):
        rule = _match(q, c.name) or ("sic" if sic and c.sic == sic else None)
        if rule:
            hits.append({"kind": "portfolio_company", "id": c.id, "name": c.name, "rule": rule})
    for d in db.query(Deal).filter_by(tenant_id=tenant):
        if deal_scope is not None and d.name not in deal_scope:
            continue  # ethical walls: a deal the caller cannot see is not even named
        rule = _deal_rule(d, q, query.strip(), sic)
        if rule:
            hits.append({"kind": "deal", "id": d.id, "name": d.name, "rule": rule, "stage": d.stage})
    order = {"cik": 0, "lei": 0, "exact": 0, "alias": 1, "contains": 2, "sic": 3}
    hits.sort(key=lambda h: (order[h["rule"]], h["kind"], h["name"]))
    return {"query": query, "normalised": q, "seen": bool(hits), "hits": hits}
