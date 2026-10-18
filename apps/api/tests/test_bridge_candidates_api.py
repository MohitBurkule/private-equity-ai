"""EBITDA bridge workbook upload: lines land as candidates, withhold the total until each is accepted.
SYNTHETIC: company name and figures are made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_bridge_workbook import _book

c = TestClient(app)


def _upload(h, entity, data):
    return c.post("/calc/bridge-candidates", data={"entity": entity},
                  files={"file": ("bridge.xlsx", data, "application/vnd.ms-excel")}, headers=h)


def test_upload_stores_candidates_and_total_counts_only_after_review():
    h = new_tenant(c, "bridge-candidates")
    data = _book([["Reported EBITDA", "reported", 120, "FY2025"],
                  ["Legal", "add_back", 7, "FY2025"],
                  ["Interest income", "deduction", 5, "FY2025"]])
    r = _upload(h, "Synth Bridge Co", data)
    assert r.status_code == 200, r.text
    ids = r.json()["fact_ids"]
    assert len(ids) == 3
    queue = c.get("/facts/review-queue", params={"entity": "Synth Bridge Co"}, headers=h).json()
    assert queue["counts"]["auto"] == 3
    assert c.get("/calc/normalized-ebitda", params={"entity": "Synth Bridge Co", "period": "FY2025"},
                 headers=h).json()["missing"]
    for fid in ids:
        assert c.post(f"/facts/{fid}/review", json={"action": "accept"}, headers=h).status_code == 200
    total = c.get("/calc/normalized-ebitda", params={"entity": "Synth Bridge Co", "period": "FY2025"},
                  headers=h).json()
    assert total["missing"] == [] and float(total["value"]) == 122


def test_bad_file_is_422():
    h = new_tenant(c, "bridge-candidates-bad")
    assert _upload(h, "Synth Bridge Co", b"not a workbook").status_code == 422
