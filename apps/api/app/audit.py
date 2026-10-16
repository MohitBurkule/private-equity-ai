"""Append-only, hash-chained audit log. Tampering with any row breaks verify_chain()."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


def _digest(prev: str, ts: str, actor: str, action: str, payload: str) -> str:
    parts = (prev, ts, actor, action, payload)
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def log_event(db: Session, actor: str, action: str, payload: dict) -> AuditEvent:
    last = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).first()
    prev = last.hash if last else "0" * 64
    ts = datetime.now(UTC).isoformat()
    body = json.dumps(payload, sort_keys=True, default=str)
    ev = AuditEvent(ts=ts, actor=actor, action=action, payload=body, prev_hash=prev,
                    hash=_digest(prev, ts, actor, action, body))
    db.add(ev)
    db.commit()
    return ev


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Returns (ok, first_bad_id)."""
    prev = "0" * 64
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        if ev.prev_hash != prev or ev.hash != _digest(prev, ev.ts, ev.actor, ev.action, ev.payload):
            return False, ev.id
        prev = ev.hash
    return True, None
