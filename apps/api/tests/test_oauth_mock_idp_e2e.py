"""OAuth authorization-code flow against mock-oauth2-server (github.com/navikt/mock-oauth2-server), an open-source
IdP that runs from its jar. Skipped unless MOCK_OAUTH_URL points at a running server, e.g.
  JSON_CONFIG_PATH=config.json java -cp <classpath> no.nav.security.mock.oauth2.StandaloneMockOAuth2ServerKt
with config.json setting interactiveLogin false. The https-only rule for real providers is kept: the test swaps
only the endpoint config for the local IdP, and the redirect back to the app is never fetched."""
import http.client
import os
import urllib.parse
import urllib.request

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import app.connectors.oauth as oauth_mod
import app.main as m
from app.main import app
from tests.helpers import new_tenant

pytestmark = pytest.mark.skipif(not os.environ.get("MOCK_OAUTH_URL"), reason="mock-oauth2-server not running")

c = TestClient(app)
REDIRECT = "https://app.test"


def _local_http(url, headers):
    """Plain http, to the local IdP only. Mirrors default_http for the token call."""
    body = headers.get("X-Post-Body")
    hdrs = {k: v for k, v in headers.items() if k != "X-Post-Body"}
    req = urllib.request.Request(url, headers=hdrs, data=body.encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def test_code_flow_saves_connection_with_refresh_token(monkeypatch):
    base = os.environ["MOCK_OAUTH_URL"].rstrip("/") + "/default"
    cfg = oauth_mod.OAuthConfig("gdrive", "cid", "secret", f"{base}/authorize", f"{base}/token", "openid offline_access")
    monkeypatch.setattr(oauth_mod, "config_for", lambda name: cfg)
    monkeypatch.setenv("OAUTH_REDIRECT_BASE", REDIRECT)
    monkeypatch.setenv("OAUTH_STATE_SECRET", "x" * 40)
    monkeypatch.setenv("CONNECTOR_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(m, "CONNECTOR_HTTP", _local_http)
    h = new_tenant(c, "oauth-e2e")

    r = c.post("/oauth/gdrive/start", json={}, headers=h)
    assert r.status_code == 200, r.text
    authorize = r.json()["authorize_url"]
    assert authorize.startswith(f"{base}/authorize?")

    # The IdP redirects to the app's https callback; read the code from the Location header, do not follow it.
    # The mock IdP shows its login page for prompt=consent (a Google-style param the app sends), so the test drops it.
    parsed = urllib.parse.urlparse(authorize)
    params = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if k != "prompt"]
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    conn.request("GET", f"{parsed.path}?{urllib.parse.urlencode(params)}")
    resp = conn.getresponse()
    assert resp.status == 302
    loc = urllib.parse.urlparse(resp.getheader("Location"))
    q = dict(urllib.parse.parse_qsl(loc.query))
    assert f"{loc.scheme}://{loc.netloc}" == REDIRECT and q.get("code")

    cb = c.get(f"/oauth/gdrive/callback?code={q['code']}&state={q['state']}")
    assert cb.status_code == 201, cb.text
    assert cb.json()["connector"] == "gdrive"
    listed = [x for x in c.get("/connections", headers=h).json() if x["connector"] == "gdrive"]
    assert len(listed) == 1
