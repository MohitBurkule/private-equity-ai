"""API-key auth. The tenant comes ONLY from the key, never from client-supplied fields."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from sqlalchemy.orm import Session

from app.models import ApiKey, Tenant


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_tenant(db: Session, name: str) -> tuple[Tenant, str]:
    """Returns the tenant and the plaintext API key (shown once, only the hash is stored)."""
    t = Tenant(id=secrets.token_hex(8), name=name)
    key = "pe_" + secrets.token_urlsafe(32)
    db.add(t)
    db.flush()  # FK order is not inferred without a relationship(); Postgres enforces it
    db.add(ApiKey(key_hash=hash_key(key), tenant_id=t.id))
    db.commit()
    return t, key


def key_id(key_hash: str) -> str:
    return key_hash[:12]


def tenant_for_key(db: Session, key: str) -> str | None:
    row = db.get(ApiKey, hash_key(key))
    return row.tenant_id if row and not row.revoked else None


def add_key(db: Session, tenant_id: str) -> tuple[str, str]:
    """Additional key for rotation: issue the new one, switch clients, then revoke the old one."""
    key = "pe_" + secrets.token_urlsafe(32)
    h = hash_key(key)
    db.add(ApiKey(key_hash=h, tenant_id=tenant_id))
    db.commit()
    return key_id(h), key


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
