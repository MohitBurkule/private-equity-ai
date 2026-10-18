"""Re-sync alerts per saved connection: an inbox item when a connector's last run is older than its limit, or
when its last run failed. The limit is per connection, set as `stale_after_hours` in the connection's options
(default 24). A connection that has never run raises nothing: there is no last run to measure from.

Each alert is keyed on the connection and its last run, so repeated checks of the same state add nothing."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Alert, Connection

DEFAULT_STALE_HOURS = 24.0


def stale_after(options: str | None) -> float:
    """The connection's limit in hours. A missing, non-numeric or non-positive value falls back to the default."""
    try:
        hours = float(json.loads(options or "{}").get("stale_after_hours", DEFAULT_STALE_HOURS))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_STALE_HOURS
    return hours if hours > 0 else DEFAULT_STALE_HOURS


def _when(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def problem(row: Connection, now: datetime) -> tuple[str, str] | None:
    """(kind, reason) for a connection that needs a person's attention, else None."""
    if row.last_run is None:
        return None
    if not (row.last_status or "").startswith("ok"):
        return "connector_error", f"last run failed: {row.last_status or 'no message'}"
    age = now - _when(row.last_run)
    limit = stale_after(row.options)
    if age > timedelta(hours=limit):
        return "connector_stale", f"last successful run {age.total_seconds() / 3600:.0f} h ago (limit {limit:g} h)"
    return None


def check(db: Session, tenant_id: str, now: datetime | None = None) -> list[Alert]:
    """Writes one warning alert per connection with a problem, skipping any already raised for the same last run."""
    now = now or datetime.now(UTC)
    raised = []
    for row in db.query(Connection).filter_by(tenant_id=tenant_id).all():
        found = problem(row, now)
        if found is None:
            continue
        kind, reason = found
        key = f"resync:{kind}:{row.id}:{row.last_run}"
        if db.query(Alert).filter_by(tenant_id=tenant_id, dedupe_key=key).first():
            continue
        alert = Alert(tenant_id=tenant_id, kind=kind, severity="warning",
                      title=f"{row.connector} needs attention" + (f" for {row.deal}" if row.deal else ""),
                      detail=reason, dedupe_key=key, fact_ids="[]", status="new",
                      created_at=now.isoformat(timespec="seconds"))
        db.add(alert)
        raised.append(alert)
    db.commit()
    return raised
