"""Route ingested emails to deals. An email with no deal is attached when exactly one deal matches it: by the
deal's name, one of its aliases, its CIK or LEI, or the website domain of a target with the deal's name. Matches
use the word rules of the email-links view. An email that matches no deal, or two or more, stays unattached in the
review queue (GET /email/review) until someone attaches it by hand.

Deals under MNPI are never an automatic target, so routing never puts an email into a deal the caller cannot see.
Attaching an email to a deal does narrow who sees it: only keys scoped to that deal see a deal's documents."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.email_links import EMAIL_CONNECTORS, _hit, company_terms
from app.models import Deal, Document, DocumentSource, Target


def deal_terms(d: Deal, targets: list[Target]) -> list[tuple[str, str]]:
    """(kind, term) pairs that name one deal in an email: its name, its aliases, its registry ids, its domain."""
    terms = company_terms(d.name, targets)
    for alias in (a.strip() for a in (d.aliases or "").split(",")):
        if alias:
            terms.append(("alias", alias))
    if d.cik:
        terms.append(("cik", d.cik.lstrip("0")))
    if d.lei:
        terms.append(("lei", d.lei))
    return terms


def _term_hit(text: str, kind: str, term: str) -> bool:
    if kind == "cik":  # the filer's id is written with or without leading zeros
        return re.search(rf"(?<!\d)0*{re.escape(term)}(?!\d)", text) is not None
    if kind == "lei":
        return _hit(text, "domain", term)  # a 20-character id, not inside a longer word
    return _hit(text, "name" if kind in ("name", "alias") else "domain", term)


def matched_deals(
    text: str, deals: list[tuple[str, list[tuple[str, str]]]]
) -> set[str]:
    return {
        name
        for name, terms in deals
        if any(_term_hit(text, kind, term) for kind, term in terms)
    }


def _email_text(doc: Document) -> str:
    return "\n".join(p.text for p in sorted(doc.pages, key=lambda p: p.number))


def route_emails(db: Session, tenant_id: str, docs: list[Document]) -> dict[str, list]:
    """Attach each unattached email that names exactly one non-MNPI deal. Returns what was attached and what waits."""
    targets = db.query(Target).filter_by(tenant_id=tenant_id).all()
    deals = [
        (d.name, deal_terms(d, targets))
        for d in db.query(Deal).filter_by(tenant_id=tenant_id, mnpi=False)
    ]
    out: dict[str, list] = {"attached": [], "review": []}
    for doc in docs:
        if doc.deal is not None:
            continue
        found = matched_deals(_email_text(doc), deals)
        if len(found) == 1:
            doc.deal = found.pop()
            out["attached"].append({"document_id": doc.id, "deal": doc.deal})
        else:
            out["review"].append(doc.id)
    return out


def unattached_emails(db: Session, tenant_id: str) -> list[dict]:
    """Ingested emails with no deal: the review queue. Only keys with no deal scope see these, since a deal-less
    document is visible to them alone."""
    email_ids = db.query(DocumentSource.document_id).filter(
        DocumentSource.connector.in_(EMAIL_CONNECTORS)
    )
    docs = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.deal.is_(None),
            Document.id.in_(email_ids),
        )
        .order_by(Document.id)
        .all()
    )
    url_of = {
        s.document_id: s.url
        for s in db.query(DocumentSource).filter(
            DocumentSource.document_id.in_([d.id for d in docs]),
            DocumentSource.connector.in_(EMAIL_CONNECTORS),
        )
    }
    return [
        {"document_id": d.id, "filename": d.filename, "source_url": url_of.get(d.id)}
        for d in docs
    ]
