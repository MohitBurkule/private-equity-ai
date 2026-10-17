"""iManage sync against WireMock, loaded with the SYNTHETIC stubs in deploy/mocks/wiremock/mappings/imanage.json.
Skipped unless WIREMOCK_JAR is set."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
BASE = "https://imanage.example.com/synthetic/imanage"
STUBS = Path(__file__).resolve().parents[3] / "deploy" / "mocks" / "wiremock" / "mappings" / "imanage.json"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_folder_sync_through_wiremock(wm, monkeypatch):
    import urllib.request
    for mapping in json.loads(STUBS.read_text())["mappings"]:
        req = urllib.request.Request(f"{wm.base}/__admin/mappings", data=json.dumps(mapping).encode(), method="POST",
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({BASE + "/": wm.base + "/synthetic/imanage/"}))
    h = new_tenant(c, "imanage-wm")
    body = {"token": "tok", "deal": "acme", "options": {"base_url": BASE, "folder": "F-77"}}
    out = c.post("/connectors/imanage/sync", json=body, headers=h).json()
    (d,) = out["ingested"]
    assert d["filename"] == "Acme CIM (SYNTHETIC).csv"
