"""SSO roles end to end against mock-oauth2-server (github.com/navikt/mock-oauth2-server).

Skipped unless MOCK_OAUTH_URL points at a running server. Start it with the fixed claims in
tests/mock_oauth/config.json (the role comes from the scope: "associate" or "viewer"):
  JSON_CONFIG_PATH=tests/mock_oauth/config.json java -cp <classpath> no.nav.security.mock.oauth2.StandaloneMockOAuth2ServerKt --port 8080
The app verifies the token through its JWKS endpoint, so the RS256 path runs as it would against a firm IdP.
"""
import json
import os
import urllib.parse
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.skipif(not os.environ.get("MOCK_OAUTH_URL"), reason="mock-oauth2-server not running")

c = TestClient(app)


TENANT_ID = "e2e-tenant"


def _mock_token(base: str, scope: str) -> str:
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": "pe",
                                   "client_secret": "pe-secret", "scope": scope}).encode()
    req = urllib.request.Request(f"{base}/token", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["access_token"]


def test_mock_idp_role_claims_drive_access(monkeypatch):
    base = os.environ["MOCK_OAUTH_URL"].rstrip("/") + "/default"
    monkeypatch.setenv("OIDC_ISSUER", base)
    monkeypatch.setenv("OIDC_AUDIENCE", "pe-platform")
    monkeypatch.setenv("OIDC_JWKS_URL", f"{base}/jwks")
    monkeypatch.delenv("OIDC_PUBLIC_KEY_PEM", raising=False)
    import app.oidc as oidc_mod
    from app.main import SessionLocal
    from app.models import Tenant
    oidc_mod._jwks_client.cache_clear()
    # The tenant id must match the claim the mock issues, so the row is created directly.
    with SessionLocal() as db:
        if db.get(Tenant, TENANT_ID) is None:
            db.add(Tenant(id=TENANT_ID, name="mock-idp"))
            db.commit()
    key = c.post(f"/admin/tenants/{TENANT_ID}/keys", json={"role": "admin"}, headers={"X-Admin-Token": "test-admin"})
    c.post("/deals", headers={"Authorization": f"Bearer {key.json()['api_key']}"}, json={"name": "IdpDeal"})
    analyst = {"Authorization": f"Bearer {_mock_token(base, 'openid associate')}"}
    viewer = {"Authorization": f"Bearer {_mock_token(base, 'openid viewer')}"}
    assert c.patch("/deals/IdpDeal", headers=analyst, json={"note": "from sso"}).status_code == 200
    assert c.patch("/deals/IdpDeal", headers=viewer, json={"note": "nope"}).status_code == 403
