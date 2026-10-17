"""Google Sheets pull and push against WireMock (open-source jar). Stubs follow the Sheets v4 values shapes;
the spreadsheet id and every value are SYNTHETIC. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.connectors.gsheets import GoogleSheets
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
SID = "SYN1AbCdEfGhIjKl"
SHEETS = "https://sheets.googleapis.com/"
EDIT = f"https://docs.google.com/spreadsheets/d/{SID}/edit"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def _stub_tab(wm):
    j = {"Content-Type": "application/json"}
    wm.stub("GET", {"urlPath": f"/v4/spreadsheets/{SID}/values/Deals"}, headers=j, body=json.dumps(
        {"range": "Deals!A1:B2", "values": [["Deal", "EV"], ["Atlas", "900"]]}))
    wm.stub("POST", {"urlPath": f"/v4/spreadsheets/{SID}/values:batchUpdate"}, headers=j,
            body=json.dumps({"totalUpdatedCells": 4}))


def test_tab_pull_through_sync_is_cited_and_resyncs_clean(wm, monkeypatch):
    _stub_tab(wm)
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({SHEETS: wm.base + "/"}))
    h = new_tenant(c, "gsheets-wm")
    body = {"token": "tok", "deal": "atlas", "options": {"spreadsheet": SID, "range": "Deals"}}
    out = c.post("/connectors/gsheets/sync", json=body, headers=h).json()
    (d,) = out["ingested"]
    assert d["filename"] == "gsheets-Deals.csv" and d["source_url"] == EDIT
    src = c.get(f"/documents/{d['document_id']}/source", headers=h).json()
    assert src["connector"] == "gsheets" and src["url"] == EDIT
    again = c.post("/connectors/gsheets/sync", json=body, headers=h).json()
    assert again["ingested"] == [] and again["unchanged"] == 1


def test_push_writes_the_range_and_reports_cells(wm):
    _stub_tab(wm)
    conn = GoogleSheets("tok", rewrite_http({SHEETS: wm.base + "/"}), spreadsheet=SID, range="Deals")
    assert conn.push([["Entity", "EV"], ["Atlas", 900.0], ["Beacon", 120.0]]) == 4
