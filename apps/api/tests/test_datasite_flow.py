"""Datasite room → cited fact. A SYNTHETIC room export (zip) holds a DD workbook; the sync run ingests it with its
folder path, and a fact is cited to one of its cells through /facts. Export responses are faked, not fetched."""
import io
import zipfile

from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.test_connectors import fake

c = TestClient(app)
URL = "https://acme.datasite.com/export/room42.zip"


def _export() -> bytes:
    wb = Workbook()
    wb.active["A2"], wb.active["B2"] = "Revenue FY2025 (SYNTHETIC)", 1234
    xlsx = io.BytesIO()
    wb.save(xlsx)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Financials/FY2025_audit_pack.xlsx", xlsx.getvalue())
    return buf.getvalue()


def test_room_file_becomes_a_cited_fact(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", fake({URL: _export()}))
    h = new_tenant(c, "datasite-flow")
    body = {"token": "tok", "deal": "atlas", "options": {"export_url": URL, "room": "Atlas"}}
    r = c.post("/connectors/datasite/sync", json=body, headers=h).json()
    (item,) = r["ingested"]
    assert item["filename"] == "Financials/FY2025_audit_pack.xlsx" and item["source_url"] == "https://acme.datasite.com/"
    fact = c.post("/facts", headers=h, json={"entity": "Acme", "metric": "revenue", "period": "FY2025",
                                             "value": "1234", "unit": "USD", "document_id": item["document_id"],
                                             "page": 1, "quote": "Sheet!B2: 1,234"})
    assert fact.status_code == 201, fact.text
    src = c.get(f"/documents/{item['document_id']}/source", headers=h).json()
    assert src["sync_run_id"] is not None
