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


def tenant_for_key(db: Session, key: str) -> str | None:
    row = db.get(ApiKey, hash_key(key))
    return row.tenant_id if row else None


def admin_token_ok(presented: str | None) -> bool:
    expected = os.environ.get("ADMIN_TOKEN")
    return bool(expected) and presented is not None and hmac.compare_digest(presented, expected)
