from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _company(h, name, sector=None, sic=None):
    body = {"name": name, "sector": sector, "sic": sic}
    return c.post("/portfolio/companies", headers=h, json=body).json()["id"]


def _targets(h, rows):
    c.post("/targets", headers=h, json=[{"source": "manual", "source_ref": r["name"], **r} for r in rows])


def test_sic_match_finds_a_target_outside_the_sector_label():
    h = new_tenant(c, "addon-sic")
    cid = _company(h, "Portco One", sector="Software", sic="7372")
    _targets(h, [
        {"name": "Beta Analytics", "sector": "Data platforms", "sic": "7372", "revenue": "100",
         "revenue_url": "https://example.test/b"},
        {"name": "Gamma Foods", "sector": "Food", "sic": "2000", "revenue": "100",
         "revenue_url": "https://example.test/g"},
    ])
    body = c.get(f"/portfolio/companies/{cid}/add-ons", headers=h).json()
    assert [i["name"] for i in body["items"]] == ["Beta Analytics"]
    assert body["items"][0]["matched_on"] == "sic" and body["sic"] == "7372"


def test_company_without_sector_or_sic_runs_no_search():
    h = new_tenant(c, "addon-none")
    cid = _company(h, "Portco Two")
    assert "no sector or SIC" in c.get(f"/portfolio/companies/{cid}/add-ons", headers=h).json()["note"]
