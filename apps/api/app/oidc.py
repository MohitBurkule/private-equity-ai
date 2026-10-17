"""OIDC bearer tokens: an identity provider signs a JWT that names the tenant, role and deal scope.

Why a JWT path beside API keys: people log in through the firm's identity provider, so access
should follow their account and be revoked there, not by handing out a key per person. The token
never sets the tenant on its own; the tenant must already exist here. A missing role falls back to
viewer, so an unmapped account can read at most and never write.
"""
from __future__ import annotations

import os
from functools import lru_cache

import jwt
from sqlalchemy.orm import Session

from app.acl import ROLES, Principal
from app.models import Tenant

# Identity-provider groups that map to a role when the token has no `role` claim. The highest-ranked group
# wins; an account in none of them is a viewer. Keycloak's synthetic realm uses these two names.
GROUP_ROLES = {"pe-ic-members": "partner", "pe-deal-team": "associate"}
_RANK = {"partner": 2, "associate": 1}


def role_from_groups(groups: object) -> str:
    if not isinstance(groups, list):
        return "viewer"
    mapped = [GROUP_ROLES[g] for g in groups if isinstance(g, str) and g in GROUP_ROLES]
    return max(mapped, key=_RANK.__getitem__, default="viewer")


def oidc_enabled() -> bool:
    return bool(os.environ.get("OIDC_ISSUER"))


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    # PyJWKClient caches keys itself, so a rotated signing key is picked up without a restart.
    return jwt.PyJWKClient(os.environ["OIDC_JWKS_URL"], cache_keys=True)


def _signing_key(token: str):
    static = os.environ.get("OIDC_PUBLIC_KEY_PEM")
    if static:
        # Offline and test deployments pin the provider's public key instead of fetching JWKS.
        return static
    return _jwks_client().get_signing_key_from_jwt(token).key


def oidc_principal(db: Session, token: str) -> Principal | None:
    if not oidc_enabled():
        return None
    try:
        claims = jwt.decode(
            token, _signing_key(token), algorithms=["RS256"],
            issuer=os.environ["OIDC_ISSUER"], audience=os.environ.get("OIDC_AUDIENCE", "pe-platform"),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    tenant = claims.get("tenant")
    if not isinstance(tenant, str) or db.get(Tenant, tenant) is None:
        return None
    if "role" in claims:  # an explicit role claim is taken as given; anything unknown reads as viewer
        role = claims["role"] if claims["role"] in ROLES else "viewer"
    else:
        role = role_from_groups(claims.get("groups"))
    deals = claims.get("deals")
    scope = frozenset(str(d) for d in deals) if isinstance(deals, list) else None
    email = claims.get("email")
    return Principal(tenant, role, scope, key_id=f"oidc:{claims['sub']}"[:32],
                     identity=email.lower() if isinstance(email, str) else None)
