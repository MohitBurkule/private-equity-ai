"""Roles and deal scopes (ethical walls) on top of tenant isolation.

A key has a role and an optional deal scope. Roles map to capabilities (see CAPABILITIES): what a
role may do is decided here, in one table, not in each endpoint.
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

from app.models import Deal, Document, Fact

# Why these roles: the associate/VP/partner split decides who may change a deal, and compliance must be
# able to hold and purge deals without being able to edit analysis. "analyst" is the legacy name for
# associate and stays valid so existing keys keep working. IR reads the tenant but writes nothing yet.
ROLES = ("admin", "partner", "vp", "associate", "analyst", "compliance", "ir", "viewer")

CAPABILITIES: dict[str, frozenset[str]] = {
    # Upload, extract, create facts, edit deals and checklists.
    "write": frozenset({"admin", "partner", "vp", "associate", "analyst"}),
    # Legal hold, MNPI flag, deal delete, retention purges.
    "govern": frozenset({"admin", "partner", "vp", "compliance"}),
}


@dataclass(frozen=True)
class Principal:
    tenant: str
    role: str = "associate"
    deals: frozenset[str] | None = None
    key_id: str = ""

    def can(self, capability: str) -> bool:
        return self.role in CAPABILITIES[capability]

    @property
    def can_write(self) -> bool:
        return self.can("write")

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
        hidden = hidden_deal_names(db, p)
        if not hidden:
            return None
        return {d.id for d in db.query(Document).filter(Document.tenant_id == p.tenant,
                                                          Document.deal.is_(None) | Document.deal.notin_(hidden))}
    if not p.deals:
        return set()
    return {d.id for d in db.query(Document).filter(Document.tenant_id == p.tenant,
                                                      Document.deal.in_(p.deals))}


def doc_visible(doc: Document | None, p: Principal, hidden: frozenset[str] = frozenset()) -> bool:
    return (doc is not None and doc.tenant_id == p.tenant and (p.deals is None or doc.deal in p.deals)
            and doc.deal not in hidden)


def _mnpi_deals(db: Session, tenant: str) -> list[Deal]:
    return db.query(Deal).filter_by(tenant_id=tenant, mnpi=True).all()


def _may_see_mnpi(d: Deal, p: Principal) -> bool:
    """Scoped by name, or the key that flagged the deal. Unscoped admin keys see nothing else."""
    return (p.deals is not None and d.name in p.deals) or bool(p.key_id and d.created_by == p.key_id)


def hidden_deal_names(db: Session, p: Principal) -> frozenset[str]:
    return frozenset(d.name for d in _mnpi_deals(db, p.tenant) if not _may_see_mnpi(d, p))


def deal_hidden(d: Deal, p: Principal) -> bool:
    return d.mnpi and not _may_see_mnpi(d, p)


def visible_mnpi_deal_names(db: Session, p: Principal) -> list[str]:
    return sorted(d.name for d in _mnpi_deals(db, p.tenant) if _may_see_mnpi(d, p))


def fact_visible(fact: Fact, scope: set[str] | None) -> bool:
    return scope is None or (bool(fact.sources) and all(s.document_id in scope for s in fact.sources))
