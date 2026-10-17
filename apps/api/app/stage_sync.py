"""Two-way deal-stage sync with a CRM (Salesforce opportunities, DealCloud rows).

Option `stage_map` is JSON: CRM stage name -> deal stage, one-to-one. Each linked deal keeps the stage both sides
had at the last sync. Whichever side moved since then wins:
- only the CRM moved: the deal takes the CRM's stage.
- only the deal moved: the CRM record takes the deal's stage.
- both moved to different stages: the deal's stage is kept, the CRM is updated, and a warning alert records it.
A CRM record links to a deal by name (case-insensitive) the first time it is seen. The CRM stage is taken as
the truth at that point. Records with no matching deal, or with a stage not in the map, are counted and skipped."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.models import STAGES, Alert, Deal, DealLink


def parse_map(text: str) -> dict[str, str]:
    try:
        m = json.loads(text or "{}")
    except ValueError as e:
        raise ConnectorError("stage_map must be a JSON object") from e
    if not isinstance(m, dict) or not m:
        raise ConnectorError("stage_map is required: CRM stage name -> deal stage")
    if any(v not in STAGES for v in m.values()):
        raise ConnectorError(f"stage_map targets must be deal stages {STAGES}")
    if len(set(m.values())) != len(m):
        raise ConnectorError("stage_map must map each deal stage from exactly one CRM stage")
    return m


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _conflict(db: Session, tenant: str, deal: str, crm_name: str, local: str, crm_stage: str) -> None:
    key = f"stage_conflict:{deal}:{local}:{crm_stage}"
    if db.query(Alert).filter_by(tenant_id=tenant, dedupe_key=key).first():
        return
    db.add(Alert(tenant_id=tenant, kind="stage_conflict", severity="warning",
                 title=f"{deal}: stage conflict with {crm_name} (deal {local}, CRM {crm_stage})",
                 detail=f"Both sides changed since the last sync. The deal keeps {local}; the CRM is updated to match.",
                 dedupe_key=key, fact_ids="[]", status="new", created_at=_now()))


def stage_sync(db: Session, tenant: str, conn, limit: int = 50) -> dict:
    if not hasattr(conn, "push_stage"):
        raise ConnectorError(f"{conn.name} does not support stage sync")
    mapping = parse_map(conn.opts.get("stage_map", ""))
    back = {v: k for k, v in mapping.items()}
    out = {"linked": 0, "updated": 0, "pushed": 0, "conflicts": 0, "unmapped": 0, "unmatched": 0}
    for rec in conn.fetch_stages(limit):
        crm_stage = mapping.get(rec["stage"])
        if crm_stage is None:
            out["unmapped"] += 1
            continue
        link = db.query(DealLink).filter_by(tenant_id=tenant, connector=conn.name, external_id=rec["id"]).first()
        if link is None:
            deal = db.query(Deal).filter(Deal.tenant_id == tenant,
                                         func.lower(Deal.name) == rec["name"].lower()).first() if rec["name"] else None
            if deal is None:
                out["unmatched"] += 1
                continue
            if deal.stage != crm_stage:
                deal.stage = crm_stage
                out["updated"] += 1
            db.add(DealLink(tenant_id=tenant, connector=conn.name, external_id=rec["id"], deal=deal.name,
                            last_local=crm_stage, last_external=crm_stage))
            out["linked"] += 1
            db.commit()
            continue
        deal = db.query(Deal).filter_by(tenant_id=tenant, name=link.deal).first()
        if deal is None:
            out["unmatched"] += 1
            continue
        local_moved, crm_moved = deal.stage != link.last_local, crm_stage != link.last_external
        if local_moved and crm_moved and deal.stage != crm_stage:
            out["conflicts"] += 1
            _conflict(db, tenant, deal.name, conn.label, deal.stage, rec["stage"])
            final = deal.stage
        elif local_moved:
            final = deal.stage
        elif crm_moved:
            final = crm_stage
        else:
            final = deal.stage
        if final != deal.stage:
            deal.stage = final
            out["updated"] += 1
        pushed_to = link.last_external
        if final != crm_stage and final in back:
            conn.push_stage(rec["id"], back[final])
            out["pushed"] += 1
            pushed_to = final
        elif final == crm_stage:
            pushed_to = final
        link.last_local, link.last_external = final, pushed_to
        db.commit()
    return out
