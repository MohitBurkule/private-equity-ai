import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.targets import sec_target
from tests.helpers import new_tenant

c = TestClient(app)

SUB = {"cik": "0000012345", "name": "Acme Corp", "sic": "3571", "sicDescription": "Electronic Computers",
       "addresses": {"business": {"stateOrCountry": "CA", "isForeignLocation": 0}}}


def facts(rows):
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}


def row(start, end, val, form="10-K", fp="FY", accn="0000012345-24-000001"):
    return {"start": start, "end": end, "val": val, "form": form, "fp": fp, "accn": accn, "filed": end}


def test_sec_revenue_picks_latest_full_year_10k_only():
    t = sec_target(SUB, facts([row("2022-01-01", "2022-12-31", 100), row("2023-01-01", "2023-12-31", 150),
                               row("2023-10-01", "2023-12-31", 40), row("2024-01-01", "2024-06-30", 90, "10-Q", "Q2")]))
    assert t.revenue == Decimal(150) and "2023-12-31" in t.revenue_period
    assert t.revenue_url.endswith("/000001234524000001/") and t.country == "United States" and t.region == "CA"
    assert sec_target(SUB, None).revenue is None  # never guessed


CH = ("CompanyName, CompanyNumber,CompanyCategory,CompanyStatus,CountryOfOrigin,IncorporationDate,"
      "RegAddress.PostCode,SICCode.SicText_1\n"
      "Widget Ltd,01234567,Private Limited Company,Active,United Kingdom,01/02/2010,AB1 2CD,62012 - Software\n"
      "Old Ltd,07654321,Private Limited Company,Dissolved,United Kingdom,01/02/2000,ZZ9 9ZZ,62012 - Software\n")


def test_targets_flow_filters_facets_screen_and_isolation():
    h, other = new_tenant(c, "tg1"), new_tenant(c, "tg2")
    assert c.post("/targets/import/sec", headers=h, json={"submissions": SUB, "companyfacts": facts(
        [row("2023-01-01", "2023-12-31", 150)])}).json()["revenue_found"] is True
    assert c.post("/targets/import/companies-house", headers=h, json={"csv_text": CH}).json()["new"] == 1  # dissolved skipped
    assert c.post("/targets/import/sec", headers=h, json={"submissions": {}}).status_code == 422
    assert c.post("/targets", headers=h, json=[{"name": "X", "source_ref": "x", "revenue": "5"}]).status_code == 422
    r = c.post("/targets", headers=h, json=[{"name": "Beta", "source_ref": "b", "revenue": "50",
                                             "revenue_url": "http://x", "sector": "Software", "country": "France"}])
    assert r.json() == {"new": 1, "updated": 0}
    again = c.post("/targets", headers=h, json=[{"name": "Beta", "source_ref": "b", "sector": None}]).json()
    assert again["updated"] == 1
    lst = c.get("/targets?min_revenue=100", headers=h).json()
    assert [t["name"] for t in lst["items"]] == ["Acme Corp"]
    assert c.get("/targets?sector=soft", headers=h).json()["total"] == 1
    assert c.get("/targets?sector=information", headers=h).json()["total"] == 1  # Widget, SIC 62012
    f = c.get("/targets/facets", headers=h).json()
    assert f["total"] == 3 and f["revenue_unknown"] == 1
    sc = c.post("/targets/screen", headers=h, json={"sectors": ["software", "information"], "min_revenue": "10"}).json()
    by = {i["name"]: i["verdict"] for i in sc["items"]}
    assert by == {"Beta": "match", "Widget Ltd": "review"}  # unknown revenue is review; Acme sector fails
    tid = lst["items"][0]["id"]
    assert c.patch(f"/targets/{tid}", headers=h, json={"status": "bad"}).status_code == 422
    assert c.patch(f"/targets/{tid}", headers=other, json={"status": "passed"}).status_code == 404
    assert c.patch(f"/targets/{tid}", headers=h, json={"status": "contacted"}).json()["status"] == "contacted"
    assert c.get("/targets", headers=other).json()["total"] == 0
    json.dumps(sc)


def test_outreach_drafts_use_only_known_facts():
    h, other = new_tenant(c, "tg3"), new_tenant(c, "tg4")
    c.post("/targets", headers=h, json=[
        {"name": "Acme", "source_ref": "a", "sector": "Software (SIC 62012)", "revenue": "150000000",
         "currency": "USD", "revenue_period": "FY2023", "revenue_url": "http://sec/x"},
        {"name": "Bare", "source_ref": "b"}])
    ids = [t["id"] for t in c.get("/targets", headers=h).json()["items"]]
    out = c.post("/targets/outreach", headers=h, json={"target_ids": ids, "sender": "Sam", "firm": "Fund I"}).json()
    full, bare = out[0]["body"], out[1]["body"]
    assert "USD 150.0 million for FY2023 (http://sec/x)" in full and "software" in full
    assert "revenue" not in bare and "invest in" not in bare  # nothing invented for the sparse target
    assert c.post("/targets/outreach", headers=other, json={"target_ids": ids, "sender": "s", "firm": "f"}).status_code == 404


def test_sector_benchmark_excludes_unknown_and_places_target():
    h = new_tenant(c, "tg5")
    rows = [{"name": f"S{v}", "source_ref": f"s{v}", "sector": "Software", "revenue": str(v),
             "revenue_url": "http://x"} for v in (10, 20, 30, 40)]
    rows += [{"name": "NoRev", "source_ref": "nr", "sector": "Software"},
             {"name": "Other", "source_ref": "o", "sector": "Mining", "revenue": "999", "revenue_url": "http://x"}]
    c.post("/targets", headers=h, json=rows)
    tid = next(t["id"] for t in c.get("/targets?q=S30", headers=h).json()["items"])
    b = c.get(f"/targets/benchmark?sector=software&target_id={tid}", headers=h).json()
    assert b["peers"] == 3 and b["excluded_no_revenue"] == 1  # S30 is not its own peer
    assert Decimal(b["median"]) == 20 and Decimal(b["min"]) == 10 and Decimal(b["max"]) == 40
    assert b["target"]["percentile"] == 67  # 30 is above 10 and 20 of 3 peers
    assert c.get("/targets/benchmark?target_id=999999", headers=h).status_code == 404
