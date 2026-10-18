"""Exit-readiness checks from the firm's own KPI packs. SYNTHETIC: company and figures made up."""

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant
from tests.test_kpi_workbook import _pack, _upload

c = TestClient(app)


def _checks(h, cid):
    return {x["check"]: x for x in c.get(f"/portfolio/companies/{cid}/exit-readiness", headers=h).json()["checks"]}


def test_history_and_ebitda_checks_pass_or_fail_on_the_firms_own_packs():
    h = new_tenant(c, "exit-readiness")
    cid = c.post("/portfolio/companies", json={"name": "Synth Exit Co"}, headers=h).json()["id"]
    for m in range(1, 13):
        rows = [("Revenue", f"2025-{m:02d}", 100 + m, "GBP m")]
        if m == 12:
            rows.append(("Adjusted EBITDA", "2025-12", 30, "GBP m"))
        assert _upload(h, cid, _pack(rows), f"p{m}.xlsx").status_code == 200
    checks = _checks(h, cid)
    assert checks["kpi_history"]["status"] == "pass" and len(checks["kpi_history"]["fact_ids"]) == 13
    assert checks["ebitda_current"]["status"] == "pass"
    assert checks["covenants_clear"]["status"] == "not_set"


def test_short_history_fails_and_no_data_is_not_set_not_pass():
    h = new_tenant(c, "exit-readiness-short")
    cid = c.post("/portfolio/companies", json={"name": "Synth Short Co"}, headers=h).json()["id"]
    assert _checks(h, cid)["kpi_history"]["status"] == "fail"  # no data, so not a pass
    assert _checks(h, cid)["ebitda_current"]["status"] == "not_set"
    assert _upload(h, cid, _pack([("Revenue", "2026-01", 5, "GBP m")]), "q.xlsx").status_code == 200
    assert _checks(h, cid)["kpi_history"]["status"] == "fail"
    assert _checks(h, cid)["ebitda_current"]["status"] == "fail"
