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
