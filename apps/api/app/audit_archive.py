"""Audit trail growth: archive old rows to files, and optionally collapse repeated document reads.

Archiving copies rows older than the retention window to a JSON-lines file in AUDIT_ARCHIVE_DIR. Each row
keeps its prev_hash and hash, and the file ends with an anchor line (last id, last hash, count), so the
archive verifies on its own and links to the live chain. Nothing is deleted from the live table here.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AuditEvent


def retention_years() -> int:
    raw = os.environ.get("AUDIT_RETENTION_YEARS", "7")
    try:
        years = int(raw)
    except ValueError as e:
        raise ValueError("AUDIT_RETENTION_YEARS must be a whole number of years") from e
    if years < 1:
        raise ValueError("AUDIT_RETENTION_YEARS must be at least 1")
    return years


def cutoff(now: datetime | None = None, years: int | None = None) -> str:
    """Rows stamped before this are outside the retention window. A year is counted as 365 days."""
    now = now or datetime.now(UTC)
    return (now - timedelta(days=365 * (years or retention_years()))).isoformat()


def archive(db: Session, tenant_id: str, out_dir: str | Path, years: int | None = None) -> dict:
    """Write rows older than the window to one file and return where it went. Caller binds the tenant."""
    old = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id,
                                              AuditEvent.ts < cutoff(years=years))
                     .order_by(AuditEvent.id)).all()
    if not old:
        return {"archived": 0, "file": None, "cutoff": cutoff(years=years)}
    lines = [json.dumps({"id": r.id, "ts": r.ts, "actor": r.actor, "action": r.action,
                         "payload": r.payload, "prev_hash": r.prev_hash, "hash": r.hash}) for r in old]
    lines.append(json.dumps({"anchor": True, "first_id": old[0].id, "last_id": old[-1].id,
                             "last_hash": old[-1].hash, "count": len(old)}))
    body = "\n".join(lines) + "\n"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"audit-{tenant_id}-{old[0].id}-{old[-1].id}.jsonl"
    path.write_text(body)
    return {"archived": len(old), "file": str(path), "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "last_id": old[-1].id, "last_hash": old[-1].hash, "cutoff": cutoff(years=years)}


def read_dedupe_on() -> bool:
    """Off by default. When on, one document.read per person, document and hour is written."""
    return os.environ.get("AUDIT_READ_DEDUPE", "0") == "1"


def read_logged_this_hour(db: Session, tenant_id: str, actor: str, doc_id: str,
                          now: datetime | None = None) -> bool:
    hour = (now or datetime.now(UTC)).isoformat()[:13]
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.actor == actor,
                                               AuditEvent.action == "document.read",
                                               AuditEvent.ts.startswith(hour))).all()
    return any(json.loads(r.payload).get("doc_id") == doc_id for r in rows)
