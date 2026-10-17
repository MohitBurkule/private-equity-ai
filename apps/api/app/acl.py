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

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Deal, Document, DocumentSource, Fact

# Why these roles: the associate/VP/partner split decides who may change a deal, and compliance must be
# able to hold and purge deals without being able to edit analysis. "analyst" is the legacy name for
# associate and stays valid so existing keys keep working. IR reads the tenant and may upload documents (LP
# and fund material), but changes no deal state, facts or checklists.
ROLES = ("admin", "partner", "vp", "associate", "analyst", "compliance", "ir", "viewer")

CAPABILITIES: dict[str, frozenset[str]] = {
    # Upload, extract, create facts, edit deals and checklists.
    "write": frozenset({"admin", "partner", "vp", "associate", "analyst"}),
    # Add documents to a deal. IR is here and nowhere else in "write".
    "upload": frozenset({"admin", "partner", "vp", "associate", "analyst", "ir"}),
    # Legal hold, MNPI flag, retention purges.
    "govern": frozenset({"admin", "partner", "vp", "compliance"}),
    # Deleting a deal for good: admin only, and only after a request is on file (see the deletion routes).
    "purge": frozenset({"admin"}),
    # Setting or reading a deal's ethical wall: admin only, since the list names the people walled off.
    "wall": frozenset({"admin"}),
}


@dataclass(frozen=True)
class Principal:
    tenant: str
    role: str = "associate"
    deals: frozenset[str] | None = None
    key_id: str = ""
    # (deal, role) pairs that replace the key role on that one deal, e.g. a viewer key that is partner on Atlas.
    deal_roles: tuple[tuple[str, str], ...] = ()
    identity: str | None = None  # the person's external id, matched against a synced source's access list
    groups: tuple[str, ...] = ()  # external group ids the person is in, matched as "group:{id}" grants

    def role_on(self, deal: str | None) -> str:
        for d, r in self.deal_roles:
            if deal is not None and d == deal:
                return r
        return self.role

    def can(self, capability: str, deal: str | None = None) -> bool:
        return self.role_on(deal) in CAPABILITIES[capability]

    def can_anywhere(self, capability: str) -> bool:
        """True if the key may do this on some deal, so a route can load and check the deal itself."""
        return self.can(capability) or any(r in CAPABILITIES[capability] for _, r in self.deal_roles)

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


def parse_deal_roles(raw: str | None) -> tuple[tuple[str, str], ...]:
    if not raw:
        return ()
    return tuple(sorted(tuple(pair.split(":", 1)) for pair in raw.split(",") if pair.strip()))


def format_deal_roles(deal_roles: dict[str, str] | None, deals: list[str] | None) -> str | None:
    """Stored as "deal:role,deal:role". Names cannot contain ':' or ',', and an override may only name a deal
    the key can already see, so it never widens the scope."""
    if not deal_roles:
        return None
    for deal, role in deal_roles.items():
        if ":" in deal or "," in deal or not deal.strip():
            raise ValueError(f"deal name {deal!r} cannot contain ':' or ','")
        if role not in ROLES:
            raise ValueError(f"role {role!r} must be one of {ROLES}")
        if deals is not None and deal not in deals:
            raise ValueError(f"deal {deal!r} is outside the key's deal scope")
    return ",".join(f"{d}:{r}" for d, r in sorted(deal_roles.items()))


def parse_wall(raw: str | None) -> tuple[str, ...]:
    """A deal's wall: sorted, lowercased grants. Stored as JSON so an identity may hold any character."""
    return tuple(sorted(set(json.loads(raw)))) if raw else ()


def format_wall(grants: list[str]) -> str | None:
    """Normalise and store a wall. Empty means no wall (null)."""
    clean = sorted({g.strip().lower() for g in grants if g and g.strip()})
    return json.dumps(clean) if clean else None


def wall_hides(d: Deal, p: Principal) -> bool:
    """True when this deal's ethical wall names one of the principal's identity or groups."""
    return bool(d.wall) and not set(parse_wall(d.wall)).isdisjoint(principal_grants(p))


def _walled_deal_names(db: Session, p: Principal) -> frozenset[str]:
    return frozenset(d.name for d in db.query(Deal).filter(Deal.tenant_id == p.tenant, Deal.wall.isnot(None))
                     if wall_hides(d, p))


def visible_doc_ids(db: Session, p: Principal) -> set[str] | None:
    """None means unrestricted. Otherwise the set of document ids this principal may see: the deal wall, minus the
    documents whose source access list does not name this principal."""
    scope = _deal_visible_doc_ids(db, p)
    hidden = acl_hidden_doc_ids(db, p)
    if not hidden:
        return scope
    if scope is None:
        scope = {i for (i,) in db.query(Document.id).filter(Document.tenant_id == p.tenant)}
    return scope - hidden


def acl_hidden_doc_ids(db: Session, p: Principal) -> set[str]:
    """Documents a synced source restricts to named people that this principal is not on. A principal without an
    identity is on none of them, so restricted documents fail closed. A document with several sources is hidden when
    any one of them denies it."""
    hidden: set[str] = set()
    grants = principal_grants(p)
    for src in db.query(DocumentSource).filter(DocumentSource.tenant_id == p.tenant, DocumentSource.acl.isnot(None)):
        if not grants & set(json.loads(src.acl)):
            hidden.add(src.document_id)
    return hidden


def principal_grants(p: Principal) -> set[str]:
    """What this principal matches in a source's access list: their identity, and each group as "group:{id}"."""
    out = {f"group:{g.lower()}" for g in p.groups}
    if p.identity:
        out.add(p.identity.lower())
    return out


def parse_groups(raw: str | None) -> tuple[str, ...]:
    return tuple(sorted({g.strip().lower() for g in (raw or "").split(",") if g.strip()}))


def format_groups(groups: list[str] | None) -> str | None:
    if not groups:
        return None
    return ",".join(parse_groups(",".join(groups))) or None


def _deal_visible_doc_ids(db: Session, p: Principal) -> set[str] | None:
    hidden = hidden_deal_names(db, p)
    if p.deals is None:
        if not hidden:
            return None
        return {d.id for d in db.query(Document).filter(Document.tenant_id == p.tenant,
                                                          Document.deal.is_(None) | Document.deal.notin_(hidden))}
    names = set(p.deals) - hidden
    if not names:
        return set()
    return {d.id for d in db.query(Document).filter(Document.tenant_id == p.tenant, Document.deal.in_(names))}


def doc_visible(doc: Document | None, p: Principal, hidden: frozenset[str] = frozenset()) -> bool:
    return (doc is not None and doc.tenant_id == p.tenant and (p.deals is None or doc.deal in p.deals)
            and doc.deal not in hidden)


def _mnpi_deals(db: Session, tenant: str) -> list[Deal]:
    return db.query(Deal).filter_by(tenant_id=tenant, mnpi=True).all()


def _may_see_mnpi(d: Deal, p: Principal) -> bool:
    """Scoped by name, or the key that flagged the deal. Unscoped admin keys see nothing else."""
    return (p.deals is not None and d.name in p.deals) or bool(p.key_id and d.created_by == p.key_id)


def _mnpi_hidden_names(db: Session, p: Principal) -> frozenset[str]:
    return frozenset(d.name for d in _mnpi_deals(db, p.tenant) if not _may_see_mnpi(d, p))


def hidden_deal_names(db: Session, p: Principal) -> frozenset[str]:
    """Deals this principal may not see: MNPI deals outside their scope, and deals walled against them."""
    return _mnpi_hidden_names(db, p) | _walled_deal_names(db, p)


def deal_hidden(d: Deal, p: Principal) -> bool:
    return (d.mnpi and not _may_see_mnpi(d, p)) or wall_hides(d, p)


def deal_scope(db: Session, p: Principal) -> set[str] | None:
    """Deal names this principal may see, for code that reads the deal table. None means no limit.
    MNPI deals hidden from the principal are left out even when the key is unscoped."""
    hidden = hidden_deal_names(db, p)
    if p.deals is None:
        if not hidden:
            return None
        return {d.name for d in db.query(Deal).filter_by(tenant_id=p.tenant) if d.name not in hidden}
    return set(p.deals) - hidden


def mnpi_name_conflict(db: Session, p: Principal, name: str) -> bool:
    """True when `name` is the same company as a deal this principal may not see (an MNPI deal).
    Outreach to such a company would reveal the deal, so the caller refuses it."""
    from app.seen_before import normalise

    target = normalise(name)
    return any(normalise(h) == target for h in _mnpi_hidden_names(db, p))


def same_company_deals(db: Session, tenant: str, name: str) -> list[str]:
    """Other deals in the tenant whose name is the same company as `name`. A warning when a wall is set, never
    enforcement: a wall is per deal, and two deals can name one company."""
    from app.seen_before import normalise

    target = normalise(name)
    return sorted(d.name for d in db.query(Deal).filter_by(tenant_id=tenant) if d.name != name
                  and normalise(d.name) == target)


def visible_mnpi_deal_names(db: Session, p: Principal) -> list[str]:
    return sorted(d.name for d in _mnpi_deals(db, p.tenant) if _may_see_mnpi(d, p) and not wall_hides(d, p))


def fact_visible(fact: Fact, scope: set[str] | None) -> bool:
    return scope is None or (bool(fact.sources) and all(s.document_id in scope for s in fact.sources))
