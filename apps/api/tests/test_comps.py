import io
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.comps import implied_range, multiple, stats
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_stats_and_nm():
    assert multiple(Decimal(100), Decimal(0))[0] is None
    assert multiple(Decimal(100), Decimal(-5))[0] is None
    st = stats([Decimal(v) for v in (8, 10, 12, 14)])
    assert st.median == Decimal(11) and st.q1 == Decimal("9.5") and st.q3 == Decimal("12.5")
    assert implied_range("ebitda", Decimal(10), stats([Decimal(1)])).low is None  # too few peers
    assert implied_range("ebitda", Decimal(10), st).mid == Decimal(110)


def test_comps_endpoint_cited_and_abstains():
    h = new_tenant(c, "comps1")
    wb = Workbook()
    data = {"P1": (1000, 100), "P2": (1200, 100), "P3": (900, 100), "P4": (500, -20), "T": (None, 50)}
    r = 1
    for ent, (ev, e) in data.items():
        wb.active[f"A{r}"], wb.active[f"B{r}"], wb.active[f"C{r}"] = ent, ev, e
        r += 1
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(ent, metric, val, row, col):
        resp = c.post("/facts", headers=h, json={"entity": ent, "metric": metric, "period": "FY24",
                      "value": str(val), "unit": "USD", "document_id": doc, "page": 1,
                      "quote": f"Sheet!{col}{row}: {val:,}"})
        assert resp.status_code == 201, resp.text
    for i, (ent, (ev, e)) in enumerate(data.items(), 1):
        if ev:
            fact(ent, "enterprise_value", ev, i, "B")
        fact(ent, "ebitda", e, i, "C")
    body = {"target": "T", "peers": list(data), "period": "FY24", "metrics": ["ebitda"]}
    out = c.post("/calc/comps", json=body, headers=h).json()
    assert out["stats"]["ebitda"]["n"] == 3  # P4 negative EBITDA excluded
    p4 = next(p for p in out["peers"] if p["entity"] == "P4")
    assert p4["multiples"]["ebitda"] is None and "ebitda" in p4["nm"]
    im = out["implied"][0]
    assert im["target_fact_id"] and Decimal(im["mid"]) == Decimal(500)
    assert out["peers"][0]["facts"]["enterprise_value"]
    body["peers"] = ["P1", "P2", "T"]  # 2 peers: no range
    assert c.post("/calc/comps", json=body, headers=h).json()["implied"][0]["mid"] is None


def test_as_of_older_than_a_week_is_stale_and_undated_is_not_flagged():
    from app.comps import is_stale_as_of
    today = date(2026, 10, 17)
    assert not is_stale_as_of("2026-10-16", today)
    assert not is_stale_as_of(None, today)
    assert is_stale_as_of("2026-10-01", today)
    assert is_stale_as_of("not-a-date", today)


def test_comps_peer_cells_carry_source_and_flag_stale_periods():
    h = new_tenant(c, "comps_cells")
    wb = Workbook()
    for r, ent in enumerate(("Q1", "Q2", "Q3", "QT"), 1):
        wb.active[f"A{r}"], wb.active[f"B{r}"], wb.active[f"C{r}"] = ent, 1000, 100
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(ent, metric, val, period, row, col):
        resp = c.post("/facts", headers=h, json={"entity": ent, "metric": metric, "period": period,
                      "value": str(val), "unit": "USD", "document_id": doc, "page": 1,
                      "quote": f"Sheet!{col}{row}: {val:,}"})
        assert resp.status_code == 201, resp.text
    for r, ent in enumerate(("Q1", "Q2", "Q3", "QT"), 1):
        fact(ent, "enterprise_value", 1000, "FY24", r, "B")
        fact(ent, "ebitda", 100, "FY24", r, "C")
    for r, ent in enumerate(("Q1", "Q2", "Q3", "QT"), 1):
        fact(ent, "enterprise_value", 1000, "FY23", r, "B")  # older EV, used only when asked for
    out = c.post("/calc/comps", json={"target": "QT", "peers": ["Q1", "Q2", "Q3"], "period": "FY24",
                                      "metrics": ["ebitda"], "ev_period": "FY23"}, headers=h).json()
    q1 = next(p for p in out["peers"] if p["entity"] == "Q1")
    assert q1["cells"]["ev"]["period"] == "FY23" and q1["cells"]["ev"]["source"].startswith("doc ")
    assert q1["stale"] == ["ev"]  # EV as of FY23 divided into FY24 EBITDA: flagged, not silently mixed
    fresh = c.post("/calc/comps", json={"target": "QT", "peers": ["Q1"], "period": "FY24",
                                        "metrics": ["ebitda"]}, headers=h).json()
    assert fresh["peers"][0]["stale"] == []
