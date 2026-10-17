import io
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant
from tests.test_calc import setup

c = TestClient(app)
NWC_METRICS = (("current_assets", 6), ("cash", 5), ("current_liabilities", 7), ("short_term_debt", 8))


def test_nwc_peg_is_average_of_complete_periods_and_withheld_on_gap():
    h = new_tenant(c, "peg1")
    _, fact = setup(h)
    for m, row in NWC_METRICS:
        fact(m, "FY23", row)
    # FY23 NWC = (400 - 120) - (300 - 60) = 40
    gap = c.get("/calc/nwc-peg", params={"entity": "A", "periods": "FY22,FY23"}, headers=h).json()
    assert gap["ok"] is False and gap["value"] is None
    assert any(m.startswith("FY22 ") for m in gap["missing"])

    # FY24 current assets of 450 gives NWC = (450 - 120) - (300 - 60) = 90. The 450 must sit in a cited cell.
    wb = Workbook()
    wb.active["A6"], wb.active["B6"] = "current assets", 450
    b = io.BytesIO()
    wb.save(b)
    doc24 = c.post("/documents", files={"file": ("fy24.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    r = c.post("/facts", headers=h, json={"entity": "A", "metric": "current_assets", "period": "FY24",
                                          "value": "450", "unit": "USD", "document_id": doc24, "page": 1,
                                          "quote": "Sheet!B6: 450"})
    assert r.status_code == 201, r.text
    for m, row in NWC_METRICS:
        if m != "current_assets":
            fact(m, "FY24", row)
    peg = c.get("/calc/nwc-peg", params={"entity": "A", "periods": "FY23,FY24"}, headers=h).json()
    assert peg["ok"] and Decimal(peg["value"]) == Decimal("65.00")
    assert [Decimal(p["value"]) for p in peg["per_period"].values()] == [40, 90]
