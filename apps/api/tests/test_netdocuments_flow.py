"""NetDocuments workspace → sync → documents, cited to their document URL. SYNTHETIC responses in the shape documented in
app/connectors/netdocuments.py. A re-sync of unchanged documents stores nothing new."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://netdocs.example.com/synthetic/netdocuments"
ROUTES = {
    f"{BASE}/v1/workspaces/WS-41/documents": json.dumps({"items": [
        {"id": "ND-5501", "name": "Atlas Credit Memo.csv", "version": 2}]}).encode(),
    f"{BASE}/v1/documents/ND-5501/content": b"metric,value\nSYNTHETIC leverage,4.1\n",
}


def test_workspace_documents_sync_cited_and_resync_is_clean(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    h = new_tenant(c, "netdocs-flow")
    body = {"token": "tok", "deal": "atlas", "options": {"base_url": BASE, "workspace": "WS-41"}}
    first = c.post("/connectors/netdocuments/sync", json=body, headers=h)
    assert first.status_code == 200, first.text
    (item,) = first.json()["ingested"]
    assert item["filename"] == "Atlas Credit Memo.csv"
    assert item["source_url"] == f"{BASE}/v1/documents/ND-5501"
    again = c.post("/connectors/netdocuments/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1


def test_missing_workspace_is_refused(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    h = new_tenant(c, "netdocs-nows")
    r = c.post("/connectors/netdocuments/sync", json={"token": "tok", "options": {"base_url": BASE}}, headers=h)
    assert r.status_code == 502
