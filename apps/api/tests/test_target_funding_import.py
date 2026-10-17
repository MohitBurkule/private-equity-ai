"""Target funding import. SYNTHETIC: the CSV is made up and uses the legacy Crunchbase export headers."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.crunchbase import COLUMNS
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
CSV = Path(__file__).parent / "fixtures" / "crunchbase" / "funding_rounds_synthetic.csv"


def _target(h, name):
    r = c.post("/targets", json=[{"name": name, "source": "manual", "source_ref": name}], headers=h)
    assert r.status_code == 201


def _tid(h, name):
    rows = c.get("/targets", headers=h).json()["items"]
    return next(t["id"] for t in rows if t["name"] == name)


def _upload(h, tid, data: bytes, filename="funding_rounds.csv"):
    return c.post(f"/targets/{tid}/funding-import", files={"file": (filename, data, "text/csv")}, headers=h)


def test_rounds_match_target_case_insensitively_and_cite_rows():
    h = new_tenant(c, "funding-match")
    _target(h, "SYNTHETIC Atlas Labs")
    r = _upload(h, _tid(h, "SYNTHETIC Atlas Labs"), CSV.read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "SYNTHETIC Atlas Labs" and body["rows_read"] == 4
    rounds = body["rounds"]
    assert [x["round_type"] for x in rounds] == ["series_a", "series_b"]  # sorted by date, grant row not matched
    assert [x["citation"]["row"] for x in rounds] == [1, 3]
    assert rounds[1]["post_money_usd"] == "90000000.0" and rounds[0]["post_money_usd"] is None
    assert all(x["citation"]["source"] == "funding_rounds.csv" for x in rounds)


def test_no_match_returns_empty_rounds_and_no_guessing():
    h = new_tenant(c, "funding-nomatch")
    _target(h, "SYNTHETIC Gamma Co")
    r = _upload(h, _tid(h, "SYNTHETIC Gamma Co"), CSV.read_bytes())
    assert r.status_code == 200 and r.json()["rounds"] == []


def test_unknown_target_is_404():
    h = new_tenant(c, "funding-404")
    assert _upload(h, 999999, CSV.read_bytes()).status_code == 404


def test_bad_csv_is_422():
    h = new_tenant(c, "funding-bad")
    _target(h, "SYNTHETIC Delta Ltd")
    header = ",".join(COLUMNS.values())
    row = ["SYNTHETIC Delta Ltd", "seed", "not-a-date", "1.0", "", "1"]
    r = _upload(h, _tid(h, "SYNTHETIC Delta Ltd"), f"{header}\n{','.join(row)}\n".encode())
    assert r.status_code == 422
