"""Pull items from a connector into the normal ingest path, under a deal wall, with a citation record
(connector + source URL) per document. Re-syncing an unchanged item is a no-op."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.connectors.base import Connector
from app.dataroom_check import check_room, parse_required
from app.ingest import finalize_upload, ingest_any
from app.models import Alert, DocumentSource


def sync(db: Session, who, conn: Connector, deal: str | None, limit: int = 50) -> dict:
    if who.restricted and deal not in who.deals:  # fail closed, same rule as manual upload
        raise PermissionError("deal is required and must be within this key's scope")
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
                                  external_id=it.external_id, version=it.version, url=it.url))
            out["ingested"].append({"document_id": d.id, "filename": d.filename, "source_url": it.url})
        db.commit()
    if out["ingested"]:
        _alert_new_documents(db, who.tenant, conn.name, deal, out["ingested"])
    check_room(db, who.tenant, deal, parse_required(conn.opts.get("required", "")))
    return out


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
                 created_at=datetime.now(UTC).isoformat(timespec="seconds")))
    db.commit()
