from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin"}


def test_record_list_filter_and_isolation():
    h = new_tenant(c, "ev1")
    assert c.post("/evals", headers=h, json={"suite": "golden", "metrics": {"rate": 0.9, "misses": [{"id": "x1"}]}}).status_code == 201
    c.post("/evals", headers=h, json={"suite": "retrieval", "metrics": {"recall@5": 0.7}, "note": "bm25"})
    c.post("/evals", headers=h, json={"suite": "golden", "metrics": {"rate": 0.95}})
    runs = c.get("/evals", headers=h).json()
    assert [r["metrics"].get("rate") for r in runs if r["suite"] == "golden"] == [0.95, 0.9]  # newest first
    assert len(c.get("/evals", headers=h, params={"suite": "retrieval"}).json()) == 1
    assert c.get("/evals", headers=new_tenant(c, "ev2")).json() == []


def test_validation_and_viewer_cannot_record():
    h = new_tenant(c, "ev3")
    assert c.post("/evals", headers=h, json={"suite": " ", "metrics": {}}).status_code == 422
    assert c.post("/evals", headers=h, json={"suite": "s", "metrics": "x"}).status_code == 422
    tid = c.post("/admin/tenants", json={"name": "ev4"}, headers=ADMIN).json()
    viewer = c.post(f"/admin/tenants/{tid['tenant_id']}/keys", json={"role": "viewer"}, headers=ADMIN).json()["api_key"]
    assert c.post("/evals", headers={"Authorization": f"Bearer {viewer}"}, json={"suite": "s", "metrics": {}}).status_code == 403
