"""API-key auth. The tenant comes ONLY from the key, never from client-supplied fields."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from sqlalchemy.orm import Session

from app.acl import (
    ROLES,
    Principal,
    format_deal_roles,
    format_deals,
    format_groups,
    parse_deal_roles,
    parse_deals,
    parse_groups,
)
from app.models import ApiKey, Tenant


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_tenant(db: Session, name: str) -> tuple[Tenant, str]:
    """Returns the tenant and the plaintext API key (shown once, only the hash is stored)."""
    t = Tenant(id=secrets.token_hex(8), name=name)
    key = "pe_" + secrets.token_urlsafe(32)
    db.add(t)
    db.flush()  # FK order is not inferred without a relationship(); Postgres enforces it
    db.add(ApiKey(key_hash=hash_key(key), tenant_id=t.id, role="admin"))
    db.commit()
    return t, key


def key_id(key_hash: str) -> str:
    return key_hash[:12]


def tenant_for_key(db: Session, key: str) -> str | None:
    row = db.get(ApiKey, hash_key(key))
    return row.tenant_id if row and not row.revoked else None


def principal_for_key(db: Session, key: str) -> Principal | None:
    row = db.get(ApiKey, hash_key(key))
    if row is None or row.revoked:
        return None
    return Principal(row.tenant_id, row.role, parse_deals(row.deals), key_id(row.key_hash),
                     parse_deal_roles(row.deal_roles), identity=row.identity, groups=parse_groups(row.groups))


def add_key(db: Session, tenant_id: str, role: str = "analyst",
            deals: list[str] | None = None, deal_roles: dict[str, str] | None = None,
            identity: str | None = None, groups: list[str] | None = None) -> tuple[str, str]:
    """Additional key for rotation: issue the new one, switch clients, then revoke the old one."""
    key = "pe_" + secrets.token_urlsafe(32)
    h = hash_key(key)
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    db.add(ApiKey(key_hash=h, tenant_id=tenant_id, role=role, deals=format_deals(deals),
                  deal_roles=format_deal_roles(deal_roles, deals), identity=identity.lower() if identity else None,
                  groups=format_groups(groups)))
    db.commit()
    return key_id(h), key


def list_keys(db: Session, tenant_id: str) -> list[dict]:
    """Every key of a tenant with its deal wall, for the admin screen. Hashes never leave the server: a key is
    named by its key_id, the same handle revoke_key takes."""
    rows = db.query(ApiKey).filter_by(tenant_id=tenant_id).order_by(ApiKey.key_hash).all()
    return [{"key_id": key_id(r.key_hash), "role": r.role, "revoked": bool(r.revoked),
             "deals": None if (d := parse_deals(r.deals)) is None else sorted(d),
             "deal_roles": dict(parse_deal_roles(r.deal_roles))} for r in rows]


def revoke_key(db: Session, kid: str) -> bool:
    rows = [r for r in db.query(ApiKey).all() if key_id(r.key_hash) == kid]
    if len(rows) != 1:
        return False
    rows[0].revoked = True
    db.commit()
    return True


def admin_token_ok(presented: str | None) -> bool:
    expected = os.environ.get("ADMIN_TOKEN")
    return bool(expected) and presented is not None and hmac.compare_digest(presented, expected)
