"""The CSV below is a made-up layout for tests, not any platform's real export."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.holdings import parse_holdings
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)
CSV = ("Business,Shares,Price per share,Currency,Date\n"
       "Acme Ltd,100,£1.50,gbp,2022-03-01\n"
       "Beta plc,\"1,000\",0.25,GBP,\n"
       ",5,1,GBP,\n"
       "Gamma,-2,1,GBP,\n"
       "Delta,3,abc,GBP,\n"
       "Eps,3,1,GBP,01/02/2022\n"
       "Zeta,3,1,GB,\n")


def test_parse_accepts_good_rows_and_rejects_bad_ones_with_line_numbers():
    rows, errors, missing = parse_holdings(CSV)
    assert not missing and [r.company for r in rows] == ["Acme Ltd", "Beta plc"]
    assert rows[1].shares == 1000 and rows[0].currency == "GBP"
    assert [e["line"] for e in errors] == [4, 5, 6, 7, 8]


def test_missing_columns_and_no_assumed_currency():
    _, _, missing = parse_holdings("Company,Shares,Price\nA,1,1\n")
    assert missing == ["currency"]
    rows, _, missing = parse_holdings("Company,Shares,Price\nA,1,1\n", currency="eur")
    assert not missing and rows[0].currency == "EUR"
    _, _, missing = parse_holdings("a,b\n1,2\n", mapping=None)
    assert {"company", "shares", "price"} <= set(missing)


def test_mapping_overrides_header_names():
    rows, _, missing = parse_holdings("Biz;Qty;Cost\nA;2;3\n", {"company": "Biz", "shares": "Qty", "price": "Cost"}, "GBP")
    assert not missing and rows[0].price == 3


def test_import_endpoint_provenance_duplicate_and_walls():
    h = new_tenant(c, "hd1")
    r = c.post("/holdings/import", headers=h, data={"platform": "crowdcube"}, files={"file": ("h.csv", CSV, "text/csv")})
    assert r.status_code == 201 and r.json()["imported"] == 2 and r.json()["rejected"] == 5
    rows = c.get("/holdings", headers=h).json()
    assert Decimal(rows[0]["cost"]) == 150 and rows[0]["line"] == 2 and rows[0]["document_id"] == r.json()["document_id"]
    again = c.post("/holdings/import", headers=h, data={"platform": "crowdcube"}, files={"file": ("h.csv", CSV, "text/csv")})
    assert again.status_code == 409
    assert c.post("/holdings/import", headers=h, data={"platform": "x"},
                  files={"file": ("n.csv", "a,b\n1,2\n", "text/csv")}).status_code == 422
    other = new_tenant(c, "hd2")
    assert c.get("/holdings", headers=other).json() == []
    assert c.post("/holdings/import", headers=h, data={"platform": "x", "mapping": "[1]"},
                  files={"file": ("m.csv", CSV, "text/csv")}).status_code == 422
