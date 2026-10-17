import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.calc import DEBT_LIKE
from app.main import app
from tests.helpers import new_tenant
from tests.test_review import mk

c = TestClient(app)
ROWS = [("total debt", 500), ("cash", 120), ("lease liabilities", 30), ("pension deficit", 40), ("earn out", 25)]


def upload(h):
    wb = Workbook()
    for i, (label, value) in enumerate(ROWS, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = label, value
    b = io.BytesIO()
    wb.save(b)
    return c.post("/documents", files={"file": ("bridge.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]


def base(h, doc):
    mk(h, doc, "total_debt", "500", "Sheet!B1: 500")
    mk(h, doc, "cash", "120", "Sheet!B2: 120")
    mk(h, doc, "lease_liabilities", "30", "Sheet!B3: 30")


def test_adjusted_net_debt_adds_each_stated_debt_like_item_and_names_the_rest():
    h = new_tenant(c, "debt-like-add")
    doc = upload(h)
    base(h, doc)
    mk(h, doc, "pension_deficit", "40", "Sheet!B4: 40")
    mk(h, doc, "earn_out", "25", "Sheet!B5: 25")
    body = c.get("/calc/net-debt-adjusted", params={"entity": "A", "period": "FY"}, headers=h).json()
    assert body["net_debt"]["value"] == "410.000000"  # 500 + 30 leases - 120 cash
    assert body["debt_like"]["value"] == "65.000000"  # the two items stated
    assert body["adjusted"] == "475.000000"
    assert body["not_found"] == [m for _, m in DEBT_LIKE if m not in ("pension_deficit", "earn_out")]


def test_no_debt_like_item_stated_means_no_adjusted_figure_not_zero():
    h = new_tenant(c, "debt-like-none")
    doc = upload(h)
    base(h, doc)
    body = c.get("/calc/net-debt-adjusted", params={"entity": "A", "period": "FY"}, headers=h).json()
    assert body["net_debt"]["value"] == "410.000000"
    assert body["debt_like"]["value"] is None
    assert body["adjusted"] is None
    assert len(body["not_found"]) == len(DEBT_LIKE)
