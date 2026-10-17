"""Rate-move watcher: a parallel move on floating-rate debt that takes a passing interest cover below its
minimum. SYNTHETIC deal facts in a real workbook."""
import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _setup(h, ebitda, interest, floating, threshold):
    rows = [("EBITDA", ebitda), ("Interest", interest), ("Floating", floating), ("Min ICR", threshold)]
    wb = Workbook()
    for i, (k, v) in enumerate(rows, 1):
        wb.active[f"A{i}"], wb.active[f"B{i}"] = k, v
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("rm.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]

    def fact(metric, row, value, unit):
        r = c.post("/facts", headers=h, json={"entity": "Co", "metric": metric, "period": "FY24", "value": str(value),
                                              "unit": unit, "document_id": doc, "page": 1,
                                              "quote": f"Sheet!B{row}: {value}"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    co = c.post("/portfolio/companies", json={"name": "Co"}, headers=h).json()["id"]
    e, i, f = fact("ebitda", 1, ebitda, "USD"), fact("interest_expense", 2, interest, "USD"), \
        fact("floating_rate_debt", 3, floating, "USD")
    thr = fact("debt.min_interest_cover_x", 4, threshold, "x")
    c.post(f"/portfolio/companies/{co}/covenants", json={"kpi_metric": "interest_coverage", "operator": ">=",
                                                         "threshold_fact_id": thr}, headers=h)
    return e, i, f, thr


def _scan(h):
    return [a for a in c.post("/alerts/scan", headers=h).json()["created"] if a["kind"] == "covenant_scenario"]


def test_shock_that_breaks_a_passing_cover_alerts_once_with_cited_inputs():
    h = new_tenant(c, "rm1")
    # cover today 100/45 = 2.22x (passes 2.0x). +100bp on 600 = +6 interest: 100/51 = 1.96x (breaks)
    e, i, f, thr = _setup(h, ebitda=100, interest=45, floating=600, threshold=2)
    made = _scan(h)
    assert len(made) == 1 and made[0]["severity"] == "warning"
    assert set(made[0]["fact_ids"]) == {e, i, f, thr}
    assert "1.96x" in made[0]["title"] and "scenario" in made[0]["detail"]
    assert _scan(h) == []  # idempotent


def test_no_alert_when_cover_survives_the_shock_or_already_breaches():
    h = new_tenant(c, "rm2")
    _setup(h, ebitda=100, interest=40, floating=100, threshold=2)  # 2.5x today, ~2.4x stressed: fine
    assert _scan(h) == []
    h2 = new_tenant(c, "rm3")
    _setup(h2, ebitda=100, interest=60, floating=600, threshold=2)  # already below: covenant watch's job
    assert _scan(h2) == []
