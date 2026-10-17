"""Saved comps peer sets per deal: stored SEC peers, refreshed from EDGAR on demand or by the `peer_refresh` workflow."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import peers as peers_mod
from app.models import PeerSet, Target


def save(db: Session, tenant: str, deal: str, name: str, t: Target, who: str, pages: int = 3) -> PeerSet:
    """Pick peers for the target now (exact SIC, then its major group) and store them with their sources."""
    exclude = {t.source_ref.zfill(10)} if t.source == "sec" else set()
    found = peers_mod.discover_with_group(t.revenue, t.sic, exclude, pages=pages)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    row = PeerSet(tenant_id=tenant, deal=deal, name=name, target_id=t.id,
                  items=json.dumps(peers_mod.peer_items(found)), dropped="[]", refreshed_at=now,
                  created_by=who, created_at=now)
    db.add(row)
    db.commit()
    return row


def out(row: PeerSet) -> dict:
    return {"id": row.id, "deal": row.deal, "name": row.name, "target_id": row.target_id,
            "items": json.loads(row.items), "dropped": json.loads(row.dropped), "refreshed_at": row.refreshed_at}


def refresh_stored(db: Session, tenant: str, peer_set_id: int, facts_get=None) -> dict:
    """Re-read each stored peer's revenue. Peers with no current revenue move to `dropped` with the reason."""
    row = db.get(PeerSet, peer_set_id)
    if row is None or row.tenant_id != tenant:
        raise ValueError("peer set not found")
    kept, dropped = peers_mod.refresh_items(json.loads(row.items), facts_get=facts_get)
    row.items = json.dumps(kept)
    row.dropped = json.dumps(dropped)
    row.refreshed_at = datetime.now(UTC).isoformat(timespec="seconds")
    db.commit()
    return {"id": row.id, "name": row.name, "kept": len(kept), "dropped": len(dropped)}
