"""Fixtures are SYNTHETIC, shaped from the published Companies House formats."""
import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.chbulk import iter_basic_company_csv, iter_psc_snapshot, parse_officers
from app.main import app, get_ch_fetch
from tests.helpers import new_tenant

c = TestClient(app)

SNAP = "\n".join([
    json.dumps({"company_number": "01234567", "data": {
        "kind": "individual-person-with-significant-control", "name": "A Person",
        "natures_of_control": ["ownership-of-shares-25-to-50-percent"], "notified_on": "2020-01-31",
        "nationality": "British", "date_of_birth": {"month": 3, "year": 1980}}}),
    json.dumps({"company_number": "01234567", "data": {
        "kind": "corporate-entity-person-with-significant-control", "name": "Holdco Ltd",
        "ceased_on": "2022-05-01", "identification": {"registration_number": "07654321", "legal_form": "Limited"}}}),
    json.dumps({"company_number": "09999999", "data": {"kind": "weird-kind", "name": "X"}}),
    "not json",
    json.dumps({"company_number": "", "data": {}}),
])


def test_snapshot_parse_no_defaults_and_filter():
    recs = list(iter_psc_snapshot(SNAP.splitlines(), {"01234567"}))
    ok = [r for r in recs if not isinstance(r, dict)]
    assert [r.kind for r in ok] == ["individual", "corporate"]
    assert ok[0].birth_year_month == "1980-03" and ok[0].source_line == 1 and ok[0].active
    assert ok[1].notified_on is None and not ok[1].active and ok[1].registration_number == "07654321"
    errs = [r for r in recs if isinstance(r, dict)]
    assert {e["line"] for e in errs} == {4, 5}
    odd = next(r for r in iter_psc_snapshot(SNAP.splitlines()) if not isinstance(r, dict) and r.company_number == "09999999")
    assert odd.kind.startswith("unknown:") and odd.problems


def test_basic_company_csv_no_defaults():
    t = ("CompanyName, CompanyNumber,CompanyCategory,CompanyStatus,IncorporationDate,RegAddress.PostCode,SICCode.SicText_1,SICCode.SicText_2\n"
         "ACME LTD,01234567,Private Limited Company,Active,31/01/2015,AB1 2CD,62012 - Business software,\n"
         "NOSTATUS LTD,00000002,,,not a date,,,\n")
    rows = list(iter_basic_company_csv(t))
    assert rows[0].incorporated == "2015-01-31" and rows[0].sic_codes == ["62012"] and rows[0].line == 2
    assert rows[1].status is None and rows[1].category is None and rows[1].incorporated is None
    assert [r.number for r in iter_basic_company_csv(t, {"00000002"})] == ["00000002"]


def test_officers_parse():
    o = parse_officers({"items": [{"name": "DOE, Jane", "officer_role": "director", "appointed_on": "2019-02-01",
                                   "date_of_birth": {"month": 11, "year": 1975}},
                                  {"name": "SMITH, Bob", "officer_role": "secretary", "resigned_on": "2021-06-30"}]})
    assert o[0].active and o[0].birth_year_month == "1975-11" and not o[1].active


def test_endpoints_officers_psc_and_extract():
    h = new_tenant(c, "chb1")
    api = {"items": [{"name": "A Person", "kind": "individual-person-with-significant-control",
                      "notified_on": "2020-01-31", "natures_of_control": ["voting-rights-75-to-100-percent"]}]}
    app.dependency_overrides[get_ch_fetch] = lambda: (lambda url: json.dumps(api).encode())
    try:
        r = c.get("/uk/company/1234567/psc", headers=h)
        assert r.status_code == 200 and r.json()[0]["company_number"] == "01234567" and r.json()[0]["kind"] == "individual"
        assert c.get("/uk/company/1234567/officers", headers=h).status_code == 200
        assert c.get("/uk/company/!!/psc", headers=h).status_code == 422
    finally:
        app.dependency_overrides.pop(get_ch_fetch, None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("psc-snapshot.jsonl", SNAP)
    for data, name in ((SNAP.encode(), "s.jsonl"), (buf.getvalue(), "s.zip")):
        r = c.post("/uk/psc/extract", params={"companies": "1234567,5"}, files={"file": (name, data)}, headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert len(j["records"]) == 2 and j["not_in_file"] == ["00000005"] and j["unreadable_lines"] == 2
    assert c.post("/uk/psc/extract", params={"companies": ""}, files={"file": ("s", b"x")}, headers=h).status_code == 422
    assert c.get("/uk/company/1234567/psc").status_code == 401
