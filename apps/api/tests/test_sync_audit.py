"""Connector sync audit: each run records what it pulled, when, and by which connection. SYNTHETIC responses."""
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake, gmail_routes

c = TestClient(app)


def _sync(h, deal="atlas"):
    return c.post("/connectors/gmail/sync", json={"token": "tok", "deal": deal}, headers=h)


def test_run_lists_its_documents_with_source_links(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    h = new_tenant(c, "audit-ok")
    r = _sync(h)
    assert r.status_code == 200, r.text
    doc = r.json()["ingested"][0]
    runs = c.get("/sync-runs", headers=h).json()
    assert len(runs) == 1 and runs[0]["status"] == "ok" and runs[0]["ingested"] == 1
    assert runs[0]["connector"] == "gmail" and runs[0]["deal"] == "atlas" and runs[0]["connection_id"] is None
    assert runs[0]["finished_at"] and runs[0]["started_at"]
    detail = c.get(f"/sync-runs/{runs[0]['id']}", headers=h).json()
    assert [d["document_id"] for d in detail["documents"]] == [doc["document_id"]]
    assert detail["documents"][0]["source_url"] == doc["source_url"]
    assert detail["documents"][0]["filename"]
    src = c.get(f"/documents/{doc['document_id']}/source", headers=h).json()
    assert src["sync_run_id"] == runs[0]["id"]


def test_repeat_sync_is_its_own_run_with_no_new_documents(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    h = new_tenant(c, "audit-again")
    _sync(h)
    _sync(h)
    runs = c.get("/sync-runs", headers=h).json()
    assert [r["ingested"] for r in runs] == [0, 1] and runs[0]["unchanged"] == 1
    assert c.get(f"/sync-runs/{runs[0]['id']}", headers=h).json()["documents"] == []


def test_failed_sync_is_recorded_as_error(monkeypatch):
    def down(url, headers):
        raise OSError("connection reset")

    monkeypatch.setattr(m, "CONNECTOR_HTTP", down)
    h = new_tenant(c, "audit-err")
    assert _sync(h).status_code == 502
    runs = c.get("/sync-runs", headers=h).json()
    assert runs[0]["status"] == "error" and "connection reset" in runs[0]["error"]


def test_runs_are_tenant_scoped_and_unknown_run_is_404(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(gmail_routes()))
    mine, other = new_tenant(c, "audit-a"), new_tenant(c, "audit-b")
    _sync(mine)
    run_id = c.get("/sync-runs", headers=mine).json()[0]["id"]
    assert c.get("/sync-runs", headers=other).json() == []
    assert c.get(f"/sync-runs/{run_id}", headers=other).status_code == 404
    assert c.get("/sync-runs/999999", headers=mine).status_code == 404
