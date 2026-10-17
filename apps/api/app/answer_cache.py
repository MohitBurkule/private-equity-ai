"""Cached /ask answers.

The key covers the question, the document the question is about, every document the caller can see with its
content hash, and the prompt version. A document that changes gets a new hash, so answers that cited its old
text are never served again. Errors are not cached. The key does not include the model, so after a provider
change, clear the tenant's rows (or bump PROMPT_VERSION) to re-ask.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.answer import PROMPT_VERSION, Answer, Claim
from app.models import AnswerCache, Document


def visible_docs(db: Session, tenant_id: str, scope: set[str] | None) -> list[tuple[str, str]]:
    q = db.query(Document.id, Document.sha256).filter(Document.tenant_id == tenant_id)
    if scope is not None:
        q = q.filter(Document.id.in_(scope))
    return sorted((r.id, r.sha256) for r in q.all())


def key(question: str, doc_id: str | None, docs: list[tuple[str, str]]) -> str:
    payload = json.dumps({"q": question, "doc": doc_id, "docs": docs, "v": PROMPT_VERSION}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _claim(d: dict) -> Claim:
    return Claim(**d)


def get(db: Session, tenant_id: str, k: str) -> Answer | None:
    row = db.query(AnswerCache).filter_by(tenant_id=tenant_id, key=k).first()
    if row is None:
        return None
    data = json.loads(row.payload)
    return Answer(status=data["status"], claims=[_claim(c) for c in data["claims"]],
                  rejected=[_claim(c) for c in data["rejected"]], detail=data["detail"],
                  prompt_version=data["prompt_version"])


def put(db: Session, tenant_id: str, k: str, a: Answer) -> None:
    if a.status == "error":
        return  # a model that failed once may answer next time
    payload = {"status": a.status, "detail": a.detail, "prompt_version": a.prompt_version,
               "claims": [asdict(c) for c in a.claims], "rejected": [asdict(c) for c in a.rejected]}
    if db.query(AnswerCache).filter_by(tenant_id=tenant_id, key=k).first() is None:
        db.add(AnswerCache(tenant_id=tenant_id, key=k, payload=json.dumps(payload),
                           created_at=datetime.now(UTC).isoformat(timespec="seconds")))
        db.commit()
