import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.extract.rows import (
    SYSTEM,  # noqa: F401  (import check: rows module loads with qoe)
)
from app.main import app, llm_dependency
from tests.helpers import new_tenant

c = TestClient(app)
ROW = "Sheet!{}1: {} | row: EBITDA"


class Fake:
    def __init__(self, rows):
        self.rows = rows

    def complete(self, system, prompt):
        return json.dumps({"rows": self.rows})


def _bridge(h, lines):
    import io

    from openpyxl import Workbook
    wb = Workbook()
    wb.active["A1"] = "EBITDA"
    for col, v in (("B", 100), ("C", 20), ("D", 5), ("E", 125)):
        wb.active[f"{col}1"] = v
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("q.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    app.dependency_overrides[llm_dependency] = lambda: Fake(lines)
    try:
        out = c.post(f"/documents/{doc}/extract-rows", headers=h,
                     json={"schema_name": "ebitda_bridge", "period": "FY24", "entity": "Co"}).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    return out


def _line(col, num, kind, amount):
    return {"page": 1, "quote": ROW.format(col, num),
            "fields": {"period": "FY24", "item": kind, "kind": kind, "amount": amount}}


def _accept_all(h):
    for f in c.get("/facts", headers=h).json():
        if f["metric"].startswith("ebitda_bridge"):
            c.post(f"/facts/{f['id']}/review", headers=h, json={"action": "accept"})


def test_normalized_ebitda_withheld_until_reviewed_then_summed_with_one_off_flag():
    h = new_tenant(c, "qoe1")
    out = _bridge(h, [_line("B", 100, "reported", 100), _line("C", 20, "add_back", 20),
                      _line("D", 5, "deduction", 5), _line("E", 125, "adjusted", 125)])
    assert [r["status"] for r in out["rows"]] == ["accepted"] * 4
    held = c.get("/calc/normalized-ebitda", params={"entity": "Co", "period": "FY24"}, headers=h).json()
    assert held["value"] is None and held["missing"] and "not yet reviewed" in held["missing"][0]
    _accept_all(h)
    got = c.get("/calc/normalized-ebitda", params={"entity": "Co", "period": "FY24"}, headers=h).json()
    assert Decimal(got["value"]) == Decimal(115)  # 100 + 20 - 5; the stated adjusted total of 125 is not summed
    assert [i["role"] for i in got["inputs"]] == ["reported", "add_back", "deduction"]
    assert got["one_off_flags"] and Decimal(got["one_off_flags"][0]["amount"]) == Decimal(20)  # 20 > 10% of 100
