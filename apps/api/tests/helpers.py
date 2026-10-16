from fastapi.testclient import TestClient


def new_tenant(client: TestClient, name: str) -> dict[str, str]:
    r = client.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['api_key']}"}
