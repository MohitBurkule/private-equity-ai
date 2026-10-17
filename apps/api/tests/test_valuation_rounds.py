"""Round and valuation history from a user's export. SYNTHETIC rows; the parser assumes no platform layout."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.valuation_rounds import parse_rounds
from tests.helpers import new_tenant

c = TestClient(app)
CSV = (
    "company,round_date,round_type,post_money,currency\n"
    "Acme,2024-03-01,Series A,\"12,000,000\",gbp\n"
    "Acme,2025-06-30,Series B,,GBP\n"            # no value: rejected, never defaulted
    "Acme,2023-01-15,Seed,4000000,GBP\n"
    "Beta,2025-02-29,Series A,5000000,USD\n"     # not a real date: rejected
    "Gamma,2024-07-01,Series A,-1,USD\n"          # not positive: rejected
    "Gamma,2024-07-01,Series A,9000000,US\n"      # bad currency code: rejected
)


def test_parser_accepts_cited_rows_and_rejects_bad_ones_with_line_numbers():
    rows, errors, missing = parse_rounds(CSV)
    assert missing == []
    assert [(r.company, r.line, r.post_money, r.currency) for r in rows] == [
        ("Acme", 2, Decimal(12000000), "GBP"), ("Acme", 4, Decimal(4000000), "GBP")]
    assert [e["line"] for e in errors] == [3, 5, 6, 7]


def test_parser_reports_missing_columns():
    assert parse_rounds("company,round_date\nAcme,2024-01-01\n")[2] == ["round_type", "post_money", "currency"]


def test_import_endpoint_provenance_duplicate_and_isolation():
    h = new_tenant(c, "vr1")
    r = c.post("/valuation-rounds/import", headers=h, files={"file": ("r.csv", CSV, "text/csv")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["accepted"] == 2 and len(body["rejected"]) == 4
    rows = c.get("/valuation-rounds?company=Acme", headers=h).json()
    assert [v["round_date"] for v in rows] == ["2023-01-15", "2024-03-01"]  # oldest first
    assert all(v["document_id"] == body["document_id"] for v in rows)
    assert rows[1]["line"] == 2
    again = c.post("/valuation-rounds/import", headers=h, files={"file": ("r.csv", CSV, "text/csv")})
    assert again.status_code == 409
    other = new_tenant(c, "vr2")
    assert c.get("/valuation-rounds", headers=other).json() == []
    assert c.post("/valuation-rounds/import", headers=h,
                  files={"file": ("n.csv", "a,b\n1,2\n", "text/csv")}).status_code == 422
