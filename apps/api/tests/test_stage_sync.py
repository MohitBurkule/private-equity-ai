"""Two-way deal-stage sync with Salesforce. The CRM is a fake that serves a query and applies PATCH bodies;
one WireMock test runs the same calls through the real HTTP layer. WireMock tests skip without WIREMOCK_JAR."""
import json
import urllib.request

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.connectors import base
from app.connectors.crm import Salesforce
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
MAP = {"Prospecting": "sourcing", "Screening": "screening", "Negotiation": "loi", "Closed Won": "closed",
       "Due Diligence": "dd", "IC Approval": "ic"}
OPTS = {"instance_url": "https://acme.my.salesforce.com", "stage_map": json.dumps(MAP)}


class FakeCrm:
    def __init__(self):
        self.stage = "Screening"
        self.pushes = []

    def __call__(self, url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if "/query" in url:
            return json.dumps({"records": [{"Id": "006A", "Name": "Atlas", "StageName": self.stage}]}).encode()
        assert headers["X-Method"] == "PATCH"
        body = json.loads(headers["X-Post-Body"])
        self.pushes.append((url.rsplit("/", 1)[1], body["StageName"]))
        self.stage = body["StageName"]
        return b""


def _stage(h, name="Atlas"):
    return next(d["stage"] for d in c.get("/deals", headers=h).json() if d["name"] == name)


def test_two_way_stage_sync_moves_the_side_that_changed(monkeypatch):
    crm = FakeCrm()
    monkeypatch.setattr(m, "CONNECTOR_HTTP", crm)
    h = new_tenant(c, "stage-sync")
    c.post("/deals", json={"name": "Atlas", "stage": "sourcing"}, headers=h)
    body = {"token": "tok", "options": OPTS}

    first = c.post("/connectors/salesforce/stage-sync", json=body, headers=h).json()
    assert first["linked"] == 1 and _stage(h) == "screening"  # CRM is the truth at first link

    c.patch("/deals/Atlas", json={"stage": "ic"}, headers=h)  # only the deal moved
    out = c.post("/connectors/salesforce/stage-sync", json=body, headers=h).json()
    assert out["pushed"] == 1 and crm.pushes == [("006A", "IC Approval")] and crm.stage == "IC Approval"

    crm.stage = "Closed Won"  # only the CRM moved
    out = c.post("/connectors/salesforce/stage-sync", json=body, headers=h).json()
    assert _stage(h) == "closed" and out["pushed"] == 0

    c.patch("/deals/Atlas", json={"stage": "dd"}, headers=h)  # both moved, to different stages
    crm.stage = "Negotiation"
    out = c.post("/connectors/salesforce/stage-sync", json=body, headers=h).json()
    assert out["conflicts"] == 1 and _stage(h) == "dd" and crm.stage == "Due Diligence"
    alerts = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "stage_conflict"]
    assert len(alerts) == 1 and "Atlas: stage conflict with Salesforce (deal dd, CRM Negotiation)" == alerts[0]["title"]


def test_stage_sync_needs_a_valid_map_and_an_unrestricted_key(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", FakeCrm())
    h = new_tenant(c, "stage-map")
    bad = {"instance_url": OPTS["instance_url"], "stage_map": json.dumps({"A": "nowhere"})}
    r = c.post("/connectors/salesforce/stage-sync", json={"token": "tok", "options": bad}, headers=h)
    assert r.status_code == 502 and "deal stages" in r.json()["detail"]
    dup = {"instance_url": OPTS["instance_url"], "stage_map": json.dumps({"A": "dd", "B": "dd"})}
    r = c.post("/connectors/salesforce/stage-sync", json={"token": "tok", "options": dup}, headers=h)
    assert r.status_code == 502 and "exactly one" in r.json()["detail"]


def test_mapped_crm_stage_without_a_deal_is_counted_not_created(monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", FakeCrm())
    h = new_tenant(c, "stage-nomatch")
    out = c.post("/connectors/salesforce/stage-sync", json={"token": "tok", "options": OPTS}, headers=h).json()
    assert out["unmatched"] == 1 and out["linked"] == 0
    assert c.get("/deals", headers=h).json() == []


def test_x_method_header_sets_the_http_method(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen["method"], seen["body"] = req.get_method(), req.data
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    base.default_http("https://example.my.salesforce.com/x", {"X-Method": "PATCH", "X-Post-Body": "{}"})
    assert seen == {"method": "PATCH", "body": b"{}"}


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def test_salesforce_stage_read_and_patch_through_wiremock(wm):
    http = rewrite_http({"https://acme.my.salesforce.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/services/data/v60.0/query"}, body=json.dumps({"records": [
        {"Id": "006B", "Name": "Beta", "StageName": "Negotiation"}]}), headers={"Content-Type": "application/json"})
    wm.stub("PATCH", {"urlPath": "/services/data/v60.0/sobjects/Opportunity/006B"}, status=204, body="")
    conn = Salesforce("tok", http, **OPTS)
    assert conn.fetch_stages(10) == [{"id": "006B", "name": "Beta", "stage": "Negotiation"}]
    conn.push_stage("006B", "Closed Won")  # must not raise on 204
