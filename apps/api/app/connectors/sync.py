"""Pull items from a connector into the normal ingest path, under a deal wall, with a citation record
(connector + source URL) per document. Re-syncing an unchanged item is a no-op."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.calendar_events import record_events
from app.connectors.base import Connector
from app.connectors.calendar import CalendarConnector
from app.dataroom_check import check_room, parse_required
from app.ingest import finalize_upload, ingest_any
from app.models import Alert, DocumentSource, SyncRun


def sync(db: Session, who, conn: Connector, deal: str | None, limit: int = 50,
         connection_id: int | None = None) -> dict:
    if who.restricted and deal not in who.deals:  # fail closed, same rule as manual upload
        raise PermissionError("deal is required and must be within this key's scope")
    run = SyncRun(tenant_id=who.tenant, connector=conn.name, connection_id=connection_id, deal=deal,
                  started_at=_now())
    db.add(run)
    db.commit()
    try:
        out = _pull(db, who, conn, deal, limit, run.id)
    except Exception as e:
        db.rollback()
        _finish(db, run.id, "error", error=str(e)[:500])
        raise
    _finish(db, run.id, "ok", ingested=len(out["ingested"]), unchanged=out["unchanged"],
            skipped=len(out["skipped"]))
    return out


def _pull(db: Session, who, conn: Connector, deal: str | None, limit: int, run_id: int) -> dict:
    seen = {(s.external_id, s.version) for s in
            db.query(DocumentSource).filter_by(tenant_id=who.tenant, connector=conn.name)}
    out = {"ingested": [], "unchanged": 0, "skipped": []}
    for it in conn.items(limit):
        if (it.external_id, it.version) in seen:
            out["unchanged"] += 1
            continue
        res = ingest_any(db, who.tenant, it.data, it.name)
        kept, skipped = finalize_upload(db, who, res, deal)
        out["skipped"] += skipped
        for d in kept:
            db.add(DocumentSource(tenant_id=who.tenant, document_id=d.id, connector=conn.name,
                                  external_id=it.external_id, version=it.version, url=it.url, sync_run_id=run_id))
            out["ingested"].append({"document_id": d.id, "filename": d.filename, "source_url": it.url})
        db.commit()
    if out["ingested"]:
        _alert_new_documents(db, who.tenant, conn.name, deal, out["ingested"])
    check_room(db, who.tenant, deal, parse_required(conn.opts.get("required", "")))
    if isinstance(conn, CalendarConnector):
        record_events(db, who.tenant, conn.name, conn.last_events)
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _finish(db: Session, run_id: int, status: str, error: str | None = None,
            ingested: int = 0, unchanged: int = 0, skipped: int = 0) -> None:
    run = db.get(SyncRun, run_id)
    run.status, run.error, run.finished_at = status, error, _now()
    run.ingested, run.unchanged, run.skipped = ingested, unchanged, skipped
    db.commit()


def _alert_new_documents(db: Session, tenant_id: str, connector: str, deal: str | None, new: list[dict]) -> None:
    """One info alert per sync that brought in new files. The key hashes the document ids, so re-running
    the same sync cannot repeat it. Titles and details carry file names and source URLs only, never fact text."""
    ids = sorted(d["document_id"] for d in new)
    key = f"sync:{connector}:{deal or '-'}:{hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]}"
    if db.query(Alert).filter_by(tenant_id=tenant_id, dedupe_key=key).first():
        return
    lines = [f"- {d['filename']} ({d['source_url'] or 'no source link'})" for d in new]
    db.add(Alert(tenant_id=tenant_id, kind="new_documents", severity="info",
                 title=f"{len(new)} new document(s) from {connector}" + (f" for {deal}" if deal else ""),
                 detail="\n".join(lines), dedupe_key=key, fact_ids="[]", status="new",
                 created_at=_now()))
    db.commit()
