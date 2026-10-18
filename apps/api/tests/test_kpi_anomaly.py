"""Month-over-month KPI outliers, judged against the company's own history. SYNTHETIC: company and figures made up."""

from app.kpi_anomaly import judge_move
from tests.helpers import new_tenant
from tests.test_kpi_workbook import _pack, _upload, c


def test_judge_move_needs_history_and_flags_only_real_outliers():
    steady = [100, 101, 102, 103, 104, 105, 106, 107]
    assert judge_move(steady[:4], 200) is None  # too little history to judge
    _, centre, z = judge_move(steady, 108)
    assert abs(z) < 3 and round(centre, 3) == 0.01
    _, _, z_big = judge_move(steady, 200)
    assert z_big > 3


def test_outlier_month_raises_a_cited_inbox_alert_and_steady_month_does_not():
    h = new_tenant(c, "kpi-anomaly")
    cid = c.post("/portfolio/companies", json={"name": "Synth Anomaly Co"}, headers=h).json()["id"]
    for m, v in enumerate([100, 101, 102, 103, 104, 105, 106], start=1):
        assert _upload(h, cid, _pack([("Revenue", f"2026-{m:02d}", v, "GBP m")]), f"p{m}.xlsx").status_code == 200
    assert not [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "kpi_anomaly"]
    assert _upload(h, cid, _pack([("Revenue", "2026-08", 107, "GBP m")]), "p8.xlsx").status_code == 200
    assert _upload(h, cid, _pack([("Revenue", "2026-09", 220, "GBP m")]), "p9.xlsx").status_code == 200
    alerts = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "kpi_anomaly"]
    assert len(alerts) == 1
    assert "2026-09" in alerts[0]["title"] and "Synth Anomaly Co" in alerts[0]["title"]
    assert "Sep!" in alerts[0]["detail"]  # cites the pack sheet and cell
