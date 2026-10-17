"""Integrations status: each catalog row is connected, needs_key or stubbed, per tenant."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _states(h):
    return {r["name"]: (r["state"], r["detail"]) for r in c.get("/connectors", headers=h).json()}


def test_states_for_unbuilt_local_and_keyed_connectors(monkeypatch):
    for k in ("OAUTH_GMAIL_CLIENT_ID", "OAUTH_GMAIL_CLIENT_SECRET", "OAUTH_GMAIL_AUTH_URL", "OAUTH_GMAIL_TOKEN_URL"):
        monkeypatch.delenv(k, raising=False)
    h = new_tenant(c, "status")
    s = _states(h)
    assert s["linkedin-enrichment"][0] == "stubbed"
    assert s["mailpit"][0] == "connected"  # no key needed
    assert s["linkedin"][0] == "connected"  # upload source
    assert s["affinity"][0] == "needs_key"
    assert s["gmail"] == ("needs_key", "set OAUTH_GMAIL_CLIENT_ID, _CLIENT_SECRET, _AUTH_URL, _TOKEN_URL")


def test_oauth_configured_still_needs_a_key_until_connected(monkeypatch):
    monkeypatch.setenv("OAUTH_GMAIL_CLIENT_ID", "id")
    monkeypatch.setenv("OAUTH_GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OAUTH_GMAIL_AUTH_URL", "https://accounts.example.com/auth")
    monkeypatch.setenv("OAUTH_GMAIL_TOKEN_URL", "https://accounts.example.com/token")
    h = new_tenant(c, "status-oauth")
    assert _states(h)["gmail"] == ("needs_key", "add a key when you import")


def test_saved_connection_turns_connected(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("CONNECTOR_KEY", Fernet.generate_key().decode())
    h = new_tenant(c, "status-saved")
    assert _states(h)["affinity"][0] == "needs_key"
    r = c.post("/connections", json={"connector": "affinity", "token": "k", "deal": None}, headers=h)
    assert r.status_code == 201, r.text
    assert _states(h)["affinity"][0] == "connected"
