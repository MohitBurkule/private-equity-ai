from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _rev(h, doc, period, value):
    r = c.post("/facts", headers=h, json={"entity": "Co", "metric": "revenue", "period": period,
                                          "value": str(value), "unit": "USD", "document_id": doc, "page": 1,
                                          "quote": f"Sheet!B1: {value:,}"})
    assert r.status_code == 201, r.text


def test_trend_growth_and_margin_withheld_per_period_gap():
    h = new_tenant(c, "trend1")
    import io

    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "Revenue", 1000
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("rev.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    _rev(h, doc, "FY23", 1000)
    _rev(h, doc, "FY24", 1000)
    out = c.get("/calc/revenue-trend", params={"entity": "Co", "periods": "FY23,FY24,FY25"}, headers=h).json()
    fy23, fy24, fy25 = out["rows"]
    assert fy23["growth_pct"] is None and fy23["ebitda_margin_pct"] is None
    assert fy23["missing"] and fy23["missing"][0].startswith("reported EBITDA")
    assert fy24["growth_pct"] == "0.0"
    assert fy25["revenue"] is None and fy25["missing"] == ["revenue for FY25"]
