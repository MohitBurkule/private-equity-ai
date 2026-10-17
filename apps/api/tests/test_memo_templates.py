import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_snapshot_drops_the_financial_section_and_unknown_template_is_refused():
    h = new_tenant(c, "memo-tpl")
    wb = Workbook()
    wb.active["A1"], wb.active["B1"] = "Revenue", 1000
    wb.active["A2"], wb.active["B2"] = "Revenue", 1200
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("r.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    for period, value, row in (("FY23", 1000, 1), ("FY24", 1200, 2)):
        r = c.post("/facts", headers=h, json={"entity": "Co", "metric": "revenue", "period": period,
                                              "value": str(value), "unit": "USD", "document_id": doc, "page": 1,
                                              "quote": f"Sheet!B{row}: {value:,}"})
        assert r.status_code == 201, r.text
    ic = c.get("/memo/sections", params={"entity": "Co"}, headers=h).json()["markdown"]
    snap = c.get("/memo/sections", params={"entity": "Co", "template": "snapshot"}, headers=h).json()["markdown"]
    assert "## Financial summary" in ic and "## Financial summary" not in snap
    assert "## Derived (computed in code)" in snap and "revenue growth (FY24 vs FY23)" in snap
    assert c.get("/memo/sections", params={"entity": "Co", "template": "teaser"}, headers=h).status_code == 422
