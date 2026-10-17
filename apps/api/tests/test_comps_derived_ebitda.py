"""Comps EBITDA from cited operating income plus D&A when no EBITDA fact is stored. A peer missing a component gets
no multiple, and the output says it was derived."""
import io
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_ebitda_is_derived_from_cited_components_and_missing_parts_abstain():
    h = new_tenant(c, "compsder")
    wb = Workbook()
    rows = {"P1": (1000, 80, 20), "P2": (1200, 90, 10), "P3": (900, 70, 30), "T": (None, 50, 10)}
    for r, (ent, (ev, oi, da)) in enumerate(rows.items(), 1):
        wb.active[f"A{r}"], wb.active[f"B{r}"], wb.active[f"C{r}"], wb.active[f"D{r}"] = ent, ev, oi, da
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("m.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(ent, metric, val, row, col):
        resp = c.post("/facts", headers=h, json={"entity": ent, "metric": metric, "period": "FY24",
                      "value": str(val), "unit": "USD", "document_id": doc, "page": 1,
                      "quote": f"Sheet!{col}{row}: {val:,}"})
        assert resp.status_code == 201, resp.text
    for i, (ent, (ev, oi, da)) in enumerate(rows.items(), 1):
        if ev:
            fact(ent, "enterprise_value", ev, i, "B")
        fact(ent, "operating_income", oi, i, "C")
        if ent != "P3":  # P3 has no D&A, so no EBITDA
            fact(ent, "depreciation_and_amortization", da, i, "D")
    out = c.post("/calc/comps", json={"target": "T", "peers": list(rows), "period": "FY24",
                                      "metrics": ["ebitda"]}, headers=h).json()
    p1 = next(p for p in out["peers"] if p["entity"] == "P1")
    assert p1["multiples"]["ebitda"] == "10.00" and p1["derived"]["ebitda"]["components"]
    p3 = next(p for p in out["peers"] if p["entity"] == "P3")
    assert p3["multiples"]["ebitda"] is None and "ebitda" in p3["nm"]
    assert out["stats"]["ebitda"]["n"] == 2
    im = out["implied"][0]
    assert im["target_fact_id"] is None and im["derived"]["formula"] == "ebitda"
    assert Decimal(im["target_value"]) == Decimal(60)
