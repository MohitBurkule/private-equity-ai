"""DocuSign stage sync against WireMock (open-source jar). Envelopes are SYNTHETIC and follow the shape in
app/connectors/docusign.py. Skipped unless WIREMOCK_JAR is set."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
BASE = "https://docusign.example.com/synthetic"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_completed_envelope_moves_stage_through_wiremock(wm, monkeypatch):
    wm.stub("GET", {"urlPath": "/synthetic/v2.1/accounts/ACC1/envelopes",
                    "queryParameters": {"from_date": {"equalTo": "2026-09-01"}}},
            headers={"Content-Type": "application/json"}, body=json.dumps({"envelopes": [
                {"envelopeId": "W1", "status": "completed", "emailSubject": "Cedar LOI",
                 "completedDateTime": "2026-09-05"}]}))
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({BASE + "/": wm.base + "/synthetic/"}))
    h = new_tenant(c, "docusign-wm")
    c.post("/deals", headers=h, json={"name": "Cedar"})
    c.patch("/deals/Cedar", headers=h, json={"stage": "loi"})
    body = {"token": "tok", "deal": "Cedar",
            "options": {"base_url": BASE, "account": "ACC1", "from_date": "2026-09-01"}}
    out = c.post("/connectors/docusign/stage-sync", headers=h, json=body).json()
    assert out["stage_after"] == "signed" and out["envelopes"] == ["W1"]
