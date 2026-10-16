"""Pull items from a connector into the normal ingest path, under a deal wall, with a citation record
(connector + source URL) per document. Re-syncing an unchanged item is a no-op."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.connectors.base import Connector
from app.ingest import finalize_upload, ingest_any
from app.models import DocumentSource


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
    return out
