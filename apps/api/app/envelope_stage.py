"""DocuSign envelope status → deal stage. Only a completed envelope moves a deal, and it moves the deal to
'signed'. A deal only moves forward through STAGES, so a late or replayed envelope never moves it back, and a
deal already past 'signed' (closed, passed) is left alone. Declined, voided and sent envelopes change nothing."""
from __future__ import annotations

from app.models import STAGES

TARGET_STAGE = {"completed": "signed"}


def advance(current: str, status: str) -> str:
    target = TARGET_STAGE.get(status)
    if target is None or current not in STAGES:
        return current
    return target if STAGES.index(target) > STAGES.index(current) else current
