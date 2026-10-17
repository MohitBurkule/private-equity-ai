"""People enrichment from public sources. SYNTHETIC: the Companies House and SEC bodies below are made up and
shaped like the public API and filing layouts. No real person is named."""
import json

import pytest
from fastapi.testclient import TestClient

from app import people_enrich as pe
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
OFFICERS = {"items": [
    {"name": "SYNTHETIC, Alex", "officer_role": "director", "appointed_on": "2020-03-01"},
    {"name": "SYNTHETIC, Blair", "officer_role": "secretary", "appointed_on": "2018-01-01", "resigned_on": "2021-01-01"}]}
PSCS = {"items": [
    {"kind": "individual-person-with-significant-control", "name": "SYNTHETIC, Casey",
     "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2020-03-01"},
    {"kind": "corporate-entity-person-with-significant-control", "name": "SYNTHETIC HOLDCO LTD",
     "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2020-03-01"}]}


def ch_fetch(url):
    if "/officers" in url:
        return json.dumps(OFFICERS).encode()
    return json.dumps(PSCS).encode()


def test_companies_house_people_are_active_individuals_and_cited():
    people = pe.companies_house_people("12345678", ch_fetch)
    assert [p["name"] for p in people] == ["SYNTHETIC, Alex", "SYNTHETIC, Casey"]  # resigned and corporate dropped
    for p in people:
        assert p["url"].startswith("https://find-and-update.company-information.service.gov.uk/company/12345678/")
        assert p["quote"] and p["source"].startswith("Companies House")


FILING = """<html><body><p>Item 1. Business.</p>
<h2>Information about our Executive Officers</h2>
<p>Jordan Q. Example, 52, Chief Executive Officer and Director.</p>
<p>Riley Sample, 47, Chief Financial Officer.</p>
<p>Jordan Q. Example, 52, Chief Executive Officer and Director.</p>
<h2>Item 1A. Risk Factors</h2><p>Morgan Fake, 60, Chair of nothing.</p></body></html>"""


def test_sec_executives_are_deduplicated_cited_and_scoped_to_the_section():
    from app.precedent_fetch import filing_text
    out = pe.sec_executives(filing_text(FILING.encode()), "https://www.sec.gov/Archives/edgar/data/1/syn.htm", "10-K")
    assert [p["name"] for p in out] == ["Jordan Q. Example", "Riley Sample"]
    assert out[1]["role"] == "Chief Financial Officer" and out[0]["source"] == "10-K"
    assert all(p["url"].startswith("https://www.sec.gov/") and p["quote"] for p in out)


def test_sec_urls_must_be_https_on_sec_gov():
    with pytest.raises(ValueError):
        pe.sec_people("https://example.test/filing.htm", "10-K", lambda u: b"")
    with pytest.raises(ValueError):
        pe.sec_people("http://www.sec.gov/x.htm", "10-K", lambda u: b"")


def test_endpoint_returns_people_and_rejects_unknown_form(monkeypatch):
    monkeypatch.setattr(pe, "companies_house_people", lambda n, fetch=None: [
        {"name": "SYNTHETIC, Alex", "role": "director", "source": "Companies House officers",
         "url": "https://find-and-update.company-information.service.gov.uk/company/1/officers", "quote": "q"}])
    h = new_tenant(c, "people-ep")
    r = c.post("/enrich/people", json={"ch_number": "12345678"}, headers=h)
    assert r.status_code == 200 and r.json()["people"][0]["name"] == "SYNTHETIC, Alex"
    assert c.post("/enrich/people", json={"sec_form": "8-K"}, headers=h).status_code == 422
