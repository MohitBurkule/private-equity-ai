"""Competitor shares: derived from cited facts over a cited market size. No market figure, no shares."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_conflicts_dd import up

c = TestClient(app)


def fact(h, doc, row, entity, value, unit="USD", metric="revenue", period="FY23"):
    """The quote is the workbook row the figure sits on, so it is printed on the cited page."""
    r = c.post("/facts", headers=h, json={"entity": entity, "metric": metric, "period": period, "value": str(value),
                                          "unit": unit, "document_id": doc, "page": 1,
                                          "quote": f"Sheet!B{row}: {value:,}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_shares_are_derived_and_sorted_with_cited_figures():
    h = new_tenant(c, "ms1")
    doc = up(h, [("market", 1000), ("alpha", 400), ("beta", 250)], "market.xlsx")
    market = fact(h, doc, 1, "US PE software market", 1000)
    a = fact(h, doc, 2, "Alpha", 400)
    b = fact(h, doc, 3, "Beta", 250)
    out = c.get("/market/shares", headers=h, params={"market": "US PE software market", "metric": "revenue",
                                                    "period": "FY23"}).json()
    assert out["derived"] is True and out["market_fact"]["fact_id"] == market
    assert [(x["entity"], x["share_pct"]) for x in out["competitors"]] == [("Alpha", "40.0"), ("Beta", "25.0")]
    assert {x["fact_id"] for x in out["competitors"]} == {a, b}
    assert out["problems"] == []


def test_no_market_figure_means_no_shares():
    h = new_tenant(c, "ms2")
    doc = up(h, [("alpha", 400)], "market.xlsx")
    fact(h, doc, 1, "Alpha", 400)
    out = c.get("/market/shares", headers=h, params={"market": "Nowhere", "metric": "revenue",
                                                    "period": "FY23"}).json()
    assert out["competitors"] == [] and out["market_fact"] is None
    assert out["problems"]


def test_shares_over_100_percent_are_flagged_not_hidden():
    h = new_tenant(c, "ms3")
    doc = up(h, [("market", 100), ("alpha", 80), ("beta", 50)], "market.xlsx")
    fact(h, doc, 1, "Market", 100)
    fact(h, doc, 2, "Alpha", 80)
    fact(h, doc, 3, "Beta", 50)
    out = c.get("/market/shares", headers=h, params={"market": "Market", "metric": "revenue",
                                                    "period": "FY23"}).json()
    assert len(out["competitors"]) == 2
    assert any("sum to" in p for p in out["problems"])


def test_mixed_units_block_the_shares():
    h = new_tenant(c, "ms4")
    doc = up(h, [("market", 100), ("alpha", 40)], "market.xlsx")
    fact(h, doc, 1, "Market", 100)
    fact(h, doc, 2, "Alpha", 40, unit="EUR")
    out = c.get("/market/shares", headers=h, params={"market": "Market", "metric": "revenue",
                                                    "period": "FY23"}).json()
    assert out["competitors"] == []
    assert any("no shares computed" in p for p in out["problems"])
