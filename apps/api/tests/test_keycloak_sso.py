"""SSO against the local Keycloak mock (deploy/mocks/keycloak, realm firm-synthetic). Skipped unless KEYCLOAK_URL
names a running server, e.g. http://localhost:8081 after `docker compose up keycloak` or a local start with the
realm imported. The token comes from Keycloak's own password grant for a synthetic user, and the app checks its
RS256 signature against the realm's JWKS, so the groups → role mapping runs on real Keycloak claims."""
import json
import os
import urllib.parse
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Tenant

KC = os.environ.get("KEYCLOAK_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not KC, reason="KEYCLOAK_URL not set")
REALM = "firm-synthetic"
TENANT_ID = "firm-synthetic"  # the tenant claim the realm's protocol mapper hardcodes
c = TestClient(app)


def _keycloak_token(user: str, password: str) -> str:
    body = urllib.parse.urlencode({"grant_type": "password", "client_id": "pe-platform",
                                   "client_secret": "dev-only-secret", "username": user,
                                   "password": password, "scope": "openid"}).encode()
    with urllib.request.urlopen(f"{KC}/realms/{REALM}/protocol/openid-connect/token", data=body, timeout=10) as r:
        return json.loads(r.read())["access_token"]


def test_keycloak_groups_drive_roles(monkeypatch):
    base = f"{KC}/realms/{REALM}"
    monkeypatch.setenv("OIDC_ISSUER", base)
    monkeypatch.setenv("OIDC_AUDIENCE", "pe-platform")
    monkeypatch.setenv("OIDC_JWKS_URL", f"{base}/protocol/openid-connect/certs")
    monkeypatch.delenv("OIDC_PUBLIC_KEY_PEM", raising=False)
    import app.oidc as oidc_mod
    oidc_mod._jwks_client.cache_clear()
    with SessionLocal() as db:
        if db.get(Tenant, TENANT_ID) is None:
            db.add(Tenant(id=TENANT_ID, name=REALM))
            db.commit()
    admin = c.post(f"/admin/tenants/{TENANT_ID}/keys", json={"role": "admin"},
                   headers={"X-Admin-Token": "test-admin"}).json()
    name = "Keycloak Deal"
    c.post("/deals", headers={"Authorization": f"Bearer {admin['api_key']}"}, json={"name": name})
    ic = {"Authorization": f"Bearer {_keycloak_token('ic@firm.test', 'app-pass')}"}
    deal = {"Authorization": f"Bearer {_keycloak_token('deal@firm.test', 'app-pass')}"}
    # pe-ic-members → partner and pe-deal-team → associate: both may edit a deal
    assert c.patch(f"/deals/{name}", headers=ic, json={"note": "from ic"}).status_code == 200
    assert c.patch(f"/deals/{name}", headers=deal, json={"note": "from deal"}).status_code == 200
