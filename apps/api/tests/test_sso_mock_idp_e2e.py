"""SSO roles end to end against mock-oauth2-server (github.com/navikt/mock-oauth2-server).

Skipped unless MOCK_OAUTH_URL points at a running server (same setup as test_oauth_mock_idp_e2e.py).
The server issues the token with the role and tenant claims set by the test, and the app verifies it
through its JWKS endpoint, so the RS256 path runs exactly as it would against a firm IdP.
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


def _mock_token(base: str, claims: dict) -> str:
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": "pe",
                                   "client_secret": "pe-secret", "audience": "pe-platform",
                                   "claims": json.dumps(claims)}).encode()
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
    oidc_mod._jwks_client.cache_clear()
    t = c.post("/admin/tenants", json={"name": "mock-idp"}, headers={"X-Admin-Token": "test-admin"}).json()
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=admin, json={"name": "IdpDeal"})
    tid = t["tenant_id"]
    analyst = {"Authorization": f"Bearer {_mock_token(base, {'tenant': tid, 'role': 'associate'})}"}
    viewer = {"Authorization": f"Bearer {_mock_token(base, {'tenant': tid})}"}
    assert c.patch("/deals/IdpDeal", headers=analyst, json={"note": "from sso"}).status_code == 200
    assert c.patch("/deals/IdpDeal", headers=viewer, json={"note": "nope"}).status_code == 403
