import io
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
