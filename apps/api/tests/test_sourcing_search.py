import json

from fastapi.testclient import TestClient

from app import sourcing_search as ss
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
PAYLOAD = {"hits": {"hits": [
    {"_source": {"ciks": ["0001002638"], "display_names": ["OPEN TEXT CORP  (OTEX)  (CIK 0001002638)"],
                 "adsh": "0001002638-26-000068", "sics": ["7373"], "form": "10-K", "file_date": "2026-08-06"}},
    {"_source": {"ciks": ["0001002638"], "display_names": ["OPEN TEXT CORP"], "adsh": "0001002638-25-000001",
                 "sics": ["7373"], "form": "10-K", "file_date": "2025-08-06"}},
    {"_source": {"ciks": ["0000012345"], "display_names": ["ACME SOFTWARE INC  (CIK 0000012345)"],
                 "adsh": "0000012345-26-000002", "sics": ["7372"], "form": "10-K", "file_date": "2026-03-01"}},
    {"_source": {"ciks": [], "display_names": ["NO CIK"], "adsh": "x"}},
]}}


def test_parse_dedups_by_cik_and_cites_filing():
    out = ss.parse(PAYLOAD)
    assert [x.cik for x in out] == ["0001002638", "0000012345"]
    assert out[0].name == "OPEN TEXT CORP" and out[0].file_date == "2026-08-06"
    assert out[0].filing_url == "https://www.sec.gov/Archives/edgar/data/1002638/000100263826000068/"
    assert out[0].company_url.endswith("CIK=1002638")


def test_search_builds_query_per_form_with_fetch():
    seen = []

    def fake(url):
        seen.append(url)
        return json.dumps(PAYLOAD)

    out = ss.search("software", ["10-K", "10-Q"], "2026-01-01", "2026-10-01", fetch=fake)
    assert len(seen) == 2 and "forms=10-K" in seen[0] and "startdt=2026-01-01" in seen[0]
    assert len(out) == 2


def test_endpoint_marks_already_imported_and_refuses_without_agent(monkeypatch):
    h = new_tenant(c, "ss1")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    body = {"query": "software", "since": "2026-01-01", "until": "2026-10-01"}
    assert c.post("/targets/search/edgar", headers=h, json=body).status_code == 503
    monkeypatch.setenv("SEC_USER_AGENT", "pe-test test@example.com")
    monkeypatch.setattr(ss, "search", lambda q, f, s, u: ss.parse(PAYLOAD))
    r = c.post("/targets/search/edgar", headers=h, json=body).json()
    by = {i["cik"]: i for i in r["items"]}
    assert by["0000012345"]["already_imported"] is False  # source_ref is only set for SEC imports
    assert by["0001002638"]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert c.post("/targets/search/edgar", headers=h, json={**body, "forms": []}).status_code == 200
    assert c.post("/targets/search/edgar", headers=h, json={**body, "query": " "}).status_code == 422
