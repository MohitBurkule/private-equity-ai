"""Filings scored against a firm thesis, each met criterion cited to its filing. SYNTHETIC: names and figures made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
THESIS = {"sic_divisions": ["73"], "keywords": ["recurring revenue"], "min_revenue": "50000000",
          "max_revenue": "300000000"}


def test_ranks_by_met_criteria_and_cites_each_met_one():
    h = new_tenant(c, "thesis-score")
    body = {"thesis": THESIS, "filings": [
        {"url": "https://www.sec.gov/Archives/edgar/data/1/a/synth-a.htm", "name": "Synth A", "sic": "7372",
         "text": "Most of our income is recurring revenue from annual licences.", "revenue": "120000000"},
        {"url": "https://www.sec.gov/Archives/edgar/data/2/b/synth-b.htm", "name": "Synth B", "sic": "2834",
         "text": "We sell pharmaceutical products.", "revenue": "900000000"},
    ]}
    r = c.post("/sourcing/thesis-score", json=body, headers=h)
    assert r.status_code == 200, r.text
    ranked = r.json()["ranked"]
    assert [x["name"] for x in ranked] == ["Synth A", "Synth B"]
    assert ranked[0]["met"] == 3 and ranked[0]["of"] == 3
    assert all(cr["cite"] and "synth-a.htm" in cr["cite"] for cr in ranked[0]["criteria"] if cr["met"])
    b = ranked[1]
    assert b["met"] == 0
    assert {cr["criterion"]: cr["reason"] for cr in b["criteria"]}["keyword:recurring revenue"] == "not in the filing text"


def test_missing_figures_are_unmet_with_reason_not_met():
    h = new_tenant(c, "thesis-score-missing")
    body = {"thesis": {"min_revenue": "1"}, "filings": [
        {"url": "https://www.sec.gov/Archives/edgar/data/3/c/synth-c.htm", "name": "Synth C"}]}
    out = c.post("/sourcing/thesis-score", json=body, headers=h).json()["ranked"][0]
    assert out["met"] == 0 and out["criteria"][0]["reason"] == "no revenue figure in the filing"
