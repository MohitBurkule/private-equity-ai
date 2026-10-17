"""Structured calendar rows. Each event is tagged with the portfolio company whose name appears in its title
(whole words, case-insensitive) and marked a board meeting when its title says "board". An event is also tagged
with the deal whose name or alias its title names, when exactly one deal does. Only the date is kept."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import CalendarEvent, Deal
from app.portfolio import PortfolioCompany


def _named(title: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title, re.IGNORECASE) is not None


def _deal_names(db: Session, tenant_id: str) -> list[tuple[str, list[str]]]:
    out = []
    for d in db.query(Deal).filter_by(tenant_id=tenant_id):
        aliases = [a.strip() for a in (d.aliases or "").split(",") if a.strip()]
        out.append((d.name, [d.name, *aliases]))
    return out


def record_events(db: Session, tenant_id: str, source: str, events: list[dict]) -> None:
    companies = [c.name for c in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id)]
    deals = _deal_names(db, tenant_id)
    for e in events:
        title = e.get("title", "")
        company = next((n for n in companies if _named(title, n)), None)
        named = {name for name, terms in deals if any(_named(title, t) for t in terms)}
        deal = named.pop() if len(named) == 1 else None
        row = db.query(CalendarEvent).filter_by(tenant_id=tenant_id, source=source,
                                                external_id=e["external_id"]).first()
        if row is None:
            row = CalendarEvent(tenant_id=tenant_id, source=source, external_id=e["external_id"])
            db.add(row)
        row.title = title
        row.starts_at = e.get("starts_at", "")[:10]
        row.url = e.get("url", "")
        row.company = company
        row.deal = deal
        row.board = "board" in title.lower()
    db.commit()
