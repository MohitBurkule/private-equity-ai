"""Structured calendar rows. Each event is tagged with the portfolio company whose name appears in its title
(whole words, case-insensitive) and marked a board meeting when its title says "board". An event is also tagged
with the deal whose name or alias its title names, when exactly one deal does. Only the date is kept."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import CalendarEvent, Deal, DealNote
from app.portfolio import PortfolioCompany


def _named(title: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title, re.IGNORECASE) is not None


def _deal_names(db: Session, tenant_id: str) -> list[tuple[str, list[str]]]:
    out = []
    for d in db.query(Deal).filter_by(tenant_id=tenant_id):
        aliases = [a.strip() for a in (d.aliases or "").split(",") if a.strip()]
        out.append((d.name, [d.name, *aliases]))
    return out


def tag_deal(db: Session, tenant_id: str, title: str) -> str | None:
    """The one deal the title names by its name or an alias, or None when no deal or several match."""
    named = {name for name, terms in _deal_names(db, tenant_id) if any(_named(title, t) for t in terms)}
    return named.pop() if len(named) == 1 else None


def _sync_note(db: Session, row: CalendarEvent) -> None:
    """Keep one deal note per tagged meeting that has text: the note cites the event and follows its deal."""
    note = db.query(DealNote).filter_by(tenant_id=row.tenant_id, calendar_event_id=row.id).first()
    if row.deal is None or not row.body.strip():
        if note is not None:
            db.delete(note)
        return
    text = f"Meeting {row.starts_at}: {row.title}\n\n{row.body.strip()}"
    if note is None:
        note = DealNote(tenant_id=row.tenant_id, calendar_event_id=row.id, author=f"calendar:{row.source}")
        db.add(note)
    note.deal, note.body, note.source_url = row.deal, text, row.url
    note.created_at = note.created_at or datetime.now(UTC).isoformat()


def retag_deals(db: Session, tenant_id: str) -> None:
    """Re-run the deal tag over every stored meeting, after a deal is created, deleted or re-aliased."""
    for row in db.query(CalendarEvent).filter_by(tenant_id=tenant_id):
        row.deal = tag_deal(db, tenant_id, row.title)
        _sync_note(db, row)
    db.commit()


def record_events(db: Session, tenant_id: str, source: str, events: list[dict]) -> None:
    companies = [c.name for c in db.query(PortfolioCompany).filter_by(tenant_id=tenant_id)]
    for e in events:
        title = e.get("title", "")
        company = next((n for n in companies if _named(title, n)), None)
        row = db.query(CalendarEvent).filter_by(tenant_id=tenant_id, source=source,
                                                external_id=e["external_id"]).first()
        if row is None:
            row = CalendarEvent(tenant_id=tenant_id, source=source, external_id=e["external_id"])
            db.add(row)
        row.title = title
        row.starts_at = e.get("starts_at", "")[:10]
        row.url = e.get("url", "")
        row.company = company
        row.deal = tag_deal(db, tenant_id, title)
        row.body = e.get("body", "")
        row.board = "board" in title.lower()
        db.flush()
        _sync_note(db, row)
    db.commit()
