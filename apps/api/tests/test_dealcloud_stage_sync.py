"""DealCloud deal-stage sync, two-way, with a SYNTHETIC entry type 'Deal' (every firm models its own).
The fake serves rows and applies PUT bodies, the same way the Salesforce stage-sync test does."""
import json

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
SITE = "acme.dealcloud.com"
MAP = {"Sourcing": "sourcing", "Screening": "screening", "Due Diligence": "dd", "IC Review": "ic"}
OPTS = {"site": SITE, "objects": "Deal", "stage_object": "Deal", "stage_map": json.dumps(MAP)}


class FakeDealCloud:
    def __init__(self):
        self.stage = "Screening"
        self.pushes = []

    def __call__(self, url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if headers.get("X-Method") == "PUT":
            (row,) = json.loads(headers["X-Post-Body"])
            self.pushes.append((row["id"], row["stage"]))
            self.stage = row["stage"]
            return b""
        assert url == f"https://{SITE}/api/rest/v4/data/entrydata/rows/Deal?limit=50"
        return json.dumps({"rows": [{"id": "DL-2001", "name": "Atlas", "stage": self.stage}]}).encode()


def _stage(h):
    return next(d["stage"] for d in c.get("/deals", headers=h).json() if d["name"] == "Atlas")


def test_dealcloud_two_way_stage_sync_moves_the_side_that_changed(monkeypatch):
    dc = FakeDealCloud()
    monkeypatch.setattr(m, "CONNECTOR_HTTP", dc)
    h = new_tenant(c, "dealcloud-sync")
    c.post("/deals", json={"name": "Atlas", "stage": "sourcing"}, headers=h)
    body = {"token": "tok", "options": OPTS}

    first = c.post("/connectors/dealcloud/stage-sync", json=body, headers=h).json()
    assert first["linked"] == 1 and _stage(h) == "screening"  # DealCloud is the truth at first link

    c.patch("/deals/Atlas", json={"stage": "ic"}, headers=h)  # only the deal moved
    out = c.post("/connectors/dealcloud/stage-sync", json=body, headers=h).json()
    assert out["pushed"] == 1 and dc.pushes == [("DL-2001", "IC Review")] and dc.stage == "IC Review"

    dc.stage = "Due Diligence"  # only DealCloud moved
    out = c.post("/connectors/dealcloud/stage-sync", json=body, headers=h).json()
    assert _stage(h) == "dd" and out["pushed"] == 0

    c.patch("/deals/Atlas", json={"stage": "ic"}, headers=h)  # both moved, to different stages
    dc.stage = "Screening"
    out = c.post("/connectors/dealcloud/stage-sync", json=body, headers=h).json()
    assert out["conflicts"] == 1 and _stage(h) == "ic" and dc.stage == "IC Review"
    alerts = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "stage_conflict"]
    assert len(alerts) == 1 and alerts[0]["title"] == "Atlas: stage conflict with DealCloud (deal ic, CRM Screening)"
