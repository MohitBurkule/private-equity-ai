"""Structured calendar rows. Each event is tagged with the portfolio company whose name appears in its title
(whole words, case-insensitive) and marked a board meeting when its title says "board". Only the date is kept."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import CalendarEvent
from app.portfolio import PortfolioCompany


def record_events(db: Session, tenant_id: str, source: str, events: list[dict]) -> None:
    print("RECORD", source, events)
    companies = [c.name for c in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id)]
    for e in events:
        title = e.get("title", "")
        company = next((n for n in companies if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", title, re.IGNORECASE)), None)
        row = db.query(CalendarEvent).filter_by(tenant_id=tenant_id, source=source,
                                                external_id=e["external_id"]).first()
        if row is None:
            row = CalendarEvent(tenant_id=tenant_id, source=source, external_id=e["external_id"])
            db.add(row)
        row.title = title
        row.starts_at = e.get("starts_at", "")[:10]
        row.url = e.get("url", "")
        row.company = company
        row.board = "board" in title.lower()
    db.commit()
