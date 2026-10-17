"""Data-room checklist: which required documents a deal's room is still missing.

A connection passes its required documents as the `required` option, comma-separated filename patterns
(e.g. "*financials*.xlsx,*QoE*.pdf"). Patterns match the file's base name, case-insensitively, so the
room's folder layout does not matter. Each sync checks every document the deal holds, and a gap raises one
warning alert. The dedupe key hashes the missing set, so the alert repeats only when the gap changes."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Alert, Document


def parse_required(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def gaps(names: list[str], required: list[str]) -> list[str]:
    bases = [posixpath.basename(n).lower() for n in names]
    return [p for p in required if not any(fnmatch.fnmatch(b, p.lower()) for b in bases)]


def check_room(db: Session, tenant_id: str, deal: str | None, required: list[str]) -> Alert | None:
    if not deal or not required:
        return None
    names = [f for (f,) in db.query(Document.filename).filter_by(tenant_id=tenant_id, deal=deal)]
    missing = gaps(names, required)
    if not missing:
        return None
    key = f"dataroom_missing:{deal}:{hashlib.sha256(json.dumps(missing).encode()).hexdigest()[:16]}"
    if db.query(Alert).filter_by(tenant_id=tenant_id, dedupe_key=key).first():
        return None
    a = Alert(tenant_id=tenant_id, kind="dd", severity="warning",
              title=f"{deal}: {len(missing)} required data-room document(s) missing",
              detail="\n".join(f"- {p}" for p in missing), dedupe_key=key, fact_ids="[]", status="new",
              created_at=datetime.now(UTC).isoformat(timespec="seconds"), deal=deal)
    db.add(a)
    db.commit()
    return a
