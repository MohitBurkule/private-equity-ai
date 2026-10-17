"""Roles and deal scopes (ethical walls) on top of tenant isolation.

A key has a role (admin | analyst | viewer) and an optional deal scope.
- deals=None: unrestricted inside the tenant (sees every document, including unassigned ones).
- deals=[...]: sees only documents tagged with one of those deals. Untagged documents are hidden,
  so forgetting to tag fails closed. A fact is visible only if ALL its source documents are.
- viewer cannot write. Scope is applied before ranking/retrieval and again when verifying claims,
  so a model cannot cite a walled document even if it guesses an id.
Enforced in the application layer; Postgres RLS remains tenant-level (documented gap).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Document, Fact

ROLES = ("admin", "analyst", "viewer")


@dataclass(frozen=True)
class Principal:
    tenant: str
    role: str = "analyst"
    deals: frozenset[str] | None = None
    key_id: str = ""

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "analyst")

    @property
    def restricted(self) -> bool:
        return self.deals is not None


def parse_deals(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    return frozenset(d.strip() for d in raw.split(",") if d.strip())


def format_deals(deals: list[str] | None) -> str | None:
    if deals is None:
        return None
    return ",".join(sorted({d.strip() for d in deals if d.strip()}))


def visible_doc_ids(db: Session, p: Principal) -> set[str] | None:
    """None means unrestricted. Otherwise the set of document ids this principal may see."""
    if p.deals is None:
        return None
    if not p.deals:
        return set()
    return {d.id for d in db.query(Document).filter(Document.tenant_id == p.tenant,
                                                      Document.deal.in_(p.deals))}


def doc_visible(doc: Document | None, p: Principal) -> bool:
    return doc is not None and doc.tenant_id == p.tenant and (p.deals is None or doc.deal in p.deals)


def deal_hidden(deal_name: str, mnpi: bool, p: Principal) -> bool:
    """MNPI deals need an explicit deal scope. An unscoped admin key does not see them either,
    so a wall cannot be bypassed by role."""
    return mnpi and (p.deals is None or deal_name not in p.deals)


def fact_visible(fact: Fact, scope: set[str] | None) -> bool:
    return scope is None or (bool(fact.sources) and all(s.document_id in scope for s in fact.sources))
