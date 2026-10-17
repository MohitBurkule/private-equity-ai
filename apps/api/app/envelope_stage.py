"""DocuSign envelope status → deal stage. Only a completed envelope moves a deal, and it moves the deal to
'signed'. A deal only moves forward through STAGES, so a late or replayed envelope never moves it back, and a
deal already past 'signed' (closed, passed) is left alone. Declined, voided and sent envelopes change nothing."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import STAGES, Deal

TARGET_STAGE = {"completed": "signed"}


def advance(current: str, status: str) -> str:
    target = TARGET_STAGE.get(status)
    if target is None or current not in STAGES:
        return current
    return target if STAGES.index(target) > STAGES.index(current) else current


def deal_for_subject(db: Session, tenant_id: str, subject: str) -> Deal | None:
    """The deal an envelope belongs to: its subject equals the deal name or starts with the name and a space.
    When several deals match, the longest name wins, so 'Atlas Two LOI' goes to 'Atlas Two', not 'Atlas'."""
    matches = [d for d in db.query(Deal).filter_by(tenant_id=tenant_id)
               if subject == d.name or subject.startswith(d.name + " ")]
    return max(matches, key=lambda d: len(d.name), default=None)


def parse_connect(payload: object) -> tuple[str, str, str] | None:
    """(envelopeId, status, emailSubject) from a DocuSign Connect JSON event. The documented shape nests them under
    data and data.envelopeSummary; a flat body with the same keys is accepted too. None when any is missing."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    summary = data.get("envelopeSummary") if isinstance(data.get("envelopeSummary"), dict) else {}
    found = (data.get("envelopeId", payload.get("envelopeId")),
             summary.get("status", payload.get("status")),
             summary.get("emailSubject", payload.get("emailSubject")))
    if any(v is None for v in found):
        return None
    return tuple(str(v) for v in found)  # type: ignore[return-value]
