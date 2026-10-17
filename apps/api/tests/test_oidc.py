import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
ISSUER = "https://sso.example.test/realms/pe"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
PUBLIC_PEM = _key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def _token(**claims):
    now = int(time.time())
    body = {"iss": ISSUER, "aud": "pe-platform", "sub": "user-1", "exp": now + 300, "iat": now, **claims}
    return jwt.encode(body, PRIVATE_PEM, algorithm="RS256")


def _tenant(name: str) -> dict:
    return c.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"}).json()


def _sso(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_PUBLIC_KEY_PEM", PUBLIC_PEM)


def test_sso_token_for_known_tenant_is_accepted(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-ok")
    h = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], role='analyst')}"}
    assert c.post("/deals", headers=h, json={"name": "Sso Deal"}).status_code == 201


def test_sso_role_defaults_to_viewer_and_cannot_write(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-viewer")
    h = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'])}"}
    assert c.post("/deals", headers=h, json={"name": "Nope"}).status_code == 403
    assert c.get("/deals", headers=h).status_code == 200


def test_sso_deal_scope_limits_visible_deals(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-scope")
    admin = {"Authorization": f"Bearer {t['api_key']}"}
    c.post("/deals", headers=admin, json={"name": "Visible"})
    c.post("/deals", headers=admin, json={"name": "Other"})
    h = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], role='viewer', deals=['Visible'])}"}
    assert [d["name"] for d in c.get("/deals", headers=h).json()] == ["Visible"]


def test_bad_signature_expired_or_unknown_tenant_is_rejected(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-bad")
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"iss": ISSUER, "aud": "pe-platform", "sub": "x", "exp": int(time.time()) + 60,
                         "tenant": t["tenant_id"]},
                        other_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()), algorithm="RS256")
    expired = _token(tenant=t["tenant_id"], exp=int(time.time()) - 10)
    unknown = _token(tenant="no-such-tenant")
    for tok in (forged, expired, unknown):
        assert c.get("/deals", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_api_keys_still_work_with_sso_enabled(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-keys")
    assert c.get("/deals", headers={"Authorization": f"Bearer {t['api_key']}"}).status_code == 200


def test_jwt_is_ignored_when_oidc_not_configured(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    t = _tenant("sso-off")
    h = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'])}"}
    assert c.get("/deals", headers=h).status_code == 401


def test_sso_groups_map_to_roles(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-groups")
    ic = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], groups=['pe-ic-members'])}"}
    deal = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], groups=['pe-deal-team'])}"}
    both = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], groups=['pe-deal-team', 'pe-ic-members'])}"}
    other = {"Authorization": f"Bearer {_token(tenant=t['tenant_id'], groups=['some-other-group'])}"}
    assert c.post("/deals", headers=deal, json={"name": "Group Deal"}).status_code == 201
    assert c.post("/deals", headers=ic, json={"name": "Ic Deal"}).status_code == 201
    assert c.post("/deals", headers=both, json={"name": "Both Deal"}).status_code == 201
    assert c.post("/deals", headers=other, json={"name": "Other Deal"}).status_code == 403


def test_explicit_role_claim_beats_groups_and_unknown_role_is_viewer(monkeypatch):
    _sso(monkeypatch)
    t = _tenant("sso-explicit")
    tenant = t["tenant_id"]
    unknown = {"Authorization": f"Bearer {_token(tenant=tenant, role='ceo', groups=['pe-ic-members'])}"}
    assert c.post("/deals", headers=unknown, json={"name": "Nope Role"}).status_code == 403
    explicit = {"Authorization": f"Bearer {_token(tenant=tenant, role='viewer', groups=['pe-ic-members'])}"}
    assert c.post("/deals", headers=explicit, json={"name": "Nope Viewer"}).status_code == 403
