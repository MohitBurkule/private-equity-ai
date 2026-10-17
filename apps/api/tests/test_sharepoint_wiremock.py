"""SharePoint document library ingest against WireMock (open-source jar). Stubs follow the Graph drive-item
shapes; every file, name and URL is SYNTHETIC. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.connectors.graph import OneDriveSharePoint
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
SITE = "sites/SYN-SITE-ID/drive"
WEB = "https://synthetic-firm.sharepoint.test/sites/deals"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def _stub_library(wm):
    j = {"Content-Type": "application/json"}
    wm.stub("GET", {"urlPath": "/v1.0/sites/SYN-SITE-ID/drive/root/children"}, body=json.dumps({"value": [
        {"id": "F1", "name": "Atlas", "folder": {"childCount": 1}, "webUrl": WEB + "/Atlas"},
        {"id": "T1", "name": "Teaser.csv", "file": {}, "webUrl": WEB + "/Teaser.csv", "eTag": "e1"}]}), headers=j)
    wm.stub("GET", {"urlPath": "/v1.0/sites/SYN-SITE-ID/drive/items/F1/children"}, body=json.dumps({"value": [
        {"id": "C1", "name": "Financials.csv", "file": {}, "webUrl": WEB + "/Atlas/Financials.csv", "eTag": "e2"}]}),
        headers=j)
    wm.stub("GET", {"urlPath": "/v1.0/sites/SYN-SITE-ID/drive/items/T1/content"},
            body="metric,value\nSYNTHETIC revenue,1\n", headers={"Content-Type": "text/csv"})
    wm.stub("GET", {"urlPath": "/v1.0/sites/SYN-SITE-ID/drive/items/C1/content"},
            body="metric,value\nSYNTHETIC ebitda,2\n", headers={"Content-Type": "text/csv"})


def test_library_walks_folders_and_keeps_paths(wm):
    _stub_library(wm)
    http = rewrite_http({"https://graph.microsoft.com/": wm.base + "/"})
    items = list(OneDriveSharePoint("tok", http, drive=SITE).items(limit=10))
    assert sorted(i.name for i in items) == ["Atlas/Financials.csv", "Teaser.csv"]
    assert {i.url for i in items} == {WEB + "/Atlas/Financials.csv", WEB + "/Teaser.csv"}


def test_each_library_file_is_ingested_and_cited(wm, monkeypatch):
    _stub_library(wm)
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({"https://graph.microsoft.com/": wm.base + "/"}))
    h = new_tenant(c, "sharepoint-wm")
    out = c.post("/connectors/sharepoint/sync", json={"token": "tok", "deal": "atlas",
                                                       "options": {"drive": SITE}}, headers=h).json()
    urls = sorted(d["source_url"] for d in out["ingested"])
    assert urls == [WEB + "/Atlas/Financials.csv", WEB + "/Teaser.csv"]
    for d in out["ingested"]:
        src = c.get(f"/documents/{d['document_id']}/source", headers=h).json()
        assert src["connector"] == "sharepoint" and src["url"] == d["source_url"]
    again = c.post("/connectors/sharepoint/sync", json={"token": "tok", "deal": "atlas",
                                                         "options": {"drive": SITE}}, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 2
