import json
from decimal import Decimal

from app import candidate_verify as cv

FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2023-01-01", "end": "2023-12-31", "val": 150, "form": "10-K", "fp": "FY", "accn": "0000012345-24-000001"},
    {"start": "2024-01-01", "end": "2024-06-30", "val": 90, "form": "10-Q", "fp": "Q2", "accn": "0000012345-24-000002"},
]}}}}}


def test_sec_candidate_verified_from_companyfacts():
    seen = []

    def get(url):
        seen.append(url)
        return json.dumps(FACTS).encode()
    c = cv.check_url("https://www.sec.gov/Archives/edgar/data/12345/000001234524000001/", "Acme", get)
    assert c.status == "verified" and c.revenue == Decimal(150) and "2023-12-31" in c.period
    assert seen[0].endswith("CIK0000012345.json")
    assert "SEC companyfacts" in c.text()


def test_unverified_when_no_revenue_or_no_sec_link_or_network_error():
    empty = cv.check_url("https://www.sec.gov/Archives/edgar/data/12345/x/", "Acme",
                         lambda u: json.dumps({"facts": {}}).encode())
    assert empty.status == "unverified" and "no full-year" in empty.note
    ch = cv.check_url("https://find-and-update.company-information.service.gov.uk/company/01234567", "Widget")
    assert ch.status == "unverified" and "Companies House" in ch.note
    def down(u):
        raise OSError("down")
    err = cv.check_url("https://www.sec.gov/Archives/edgar/data/12345/x/", "Acme", down)
    assert err.status == "unverified" and "unavailable" in err.note


def test_ebitda_margin_clause_is_read_not_screened():
    assert cv.ebitda_margin_clause("EBITDA margin is at least 15%, and") == Decimal(15)
    assert cv.ebitda_margin_clause("revenue is at least $20 million") is None
