from fastapi.testclient import TestClient


def new_tenant(client: TestClient, name: str) -> dict[str, str]:
    r = client.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['api_key']}"}


def new_tenant_id(client: TestClient, name: str) -> tuple[dict[str, str], str]:
    """Like new_tenant, plus the tenant id, for tests that read rows back under RLS (bind_tenant first)."""
    r = client.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['api_key']}"}, r.json()["tenant_id"]
