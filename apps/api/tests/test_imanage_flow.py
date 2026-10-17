"""iManage folder → sync → documents, cited to their document URL. SYNTHETIC responses in the shape documented in
app/connectors/imanage.py. A re-sync of unchanged documents stores nothing new."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
BASE = "https://imanage.example.com/synthetic/imanage"
ROUTES = {
    f"{BASE}/v1/folders/F-77/documents": json.dumps({"items": [
        {"id": "IM-9001", "name": "Acme CIM.csv", "version": 3}]}).encode(),
    f"{BASE}/v1/documents/IM-9001/content": b"metric,value\nSYNTHETIC revenue,1\n",
}


def test_folder_documents_sync_cited_and_resync_is_clean(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    h = new_tenant(c, "imanage-flow")
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "folder": "F-77"}}
    first = c.post("/connectors/imanage/sync", json=body, headers=h)
    assert first.status_code == 200, first.text
    (item,) = first.json()["ingested"]
    assert item["filename"] == "Acme CIM.csv"
    assert item["source_url"] == f"{BASE}/v1/documents/IM-9001"
    again = c.post("/connectors/imanage/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1


def test_missing_folder_is_refused(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake(ROUTES))
    h = new_tenant(c, "imanage-nofolder")
    r = c.post("/connectors/imanage/sync", json={"token": "tok", "options": {"base_url": BASE}}, headers=h)
    assert r.status_code == 502
