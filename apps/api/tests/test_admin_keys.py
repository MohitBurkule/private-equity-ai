from fastapi.testclient import TestClient

from app.main import app

ADMIN = {"X-Admin-Token": "test-admin"}


def test_list_keys_shows_deal_walls_without_hashes(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    c = TestClient(app)
    tid = c.post("/admin/tenants", json={"name": "walls"}, headers=ADMIN).json()["tenant_id"]
    c.post(f"/admin/tenants/{tid}/keys", json={"role": "analyst", "deals": ["atlas"],
                                               "deal_roles": {"atlas": "partner"}}, headers=ADMIN)
    c.post(f"/admin/tenants/{tid}/keys", json={"role": "partner"}, headers=ADMIN)

    r = c.get(f"/admin/tenants/{tid}/keys", headers=ADMIN)
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert len(keys) == 3  # the bootstrap owner key, plus the two added here
    walled = next(k for k in keys if k["deals"] == ["atlas"])
    assert walled["deal_roles"] == {"atlas": "partner"}
    assert walled["revoked"] is False
    assert all("key_hash" not in k and "api_key" not in k for k in keys)


def test_list_keys_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    c = TestClient(app)
    tid = c.post("/admin/tenants", json={"name": "walls2"}, headers=ADMIN).json()["tenant_id"]
    assert c.get(f"/admin/tenants/{tid}/keys").status_code == 403
    assert c.get("/admin/tenants/nope/keys", headers=ADMIN).status_code == 404
