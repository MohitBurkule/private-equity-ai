"""Covenant compliance over monthly ledger periods: breach, gaps in the feed, and the tightest month."""
from app.portfolio import compliance_summary


def _t(period, status, headroom=None):
    row = {"period": period, "status": status, "value": "1", "threshold": "1", "unit": "USD"}
    if headroom is not None:
        row["headroom_pct"] = headroom
    return row


def test_no_tests_is_no_data():
    assert compliance_summary([]) == {"status": "no_data", "tested_months": 0, "first_breach": None,
                                      "latest": None, "min_headroom": None, "missing": []}


def test_gap_in_the_feed_is_listed_and_breach_is_the_first_month_that_failed():
    out = compliance_summary([_t("2026-09", "ok", "10.0"), _t("2026-07", "ok", "4.5"),
                              _t("2026-08", "breach", "-2.0"), _t("2026-12", "ok", "7.0")])
    assert out["status"] == "breach" and out["first_breach"] == "2026-08"
    assert out["missing"] == ["2026-10", "2026-11"]
    assert out["min_headroom"] == {"period": "2026-08", "headroom_pct": "-2.0"}
    assert out["latest"]["period"] == "2026-12" and out["tested_months"] == 4


def test_year_boundary_and_all_ok():
    out = compliance_summary([_t("2025-12", "ok"), _t("2026-01", "ok")])
    assert out["status"] == "ok" and out["missing"] == [] and out["min_headroom"] is None


def test_non_monthly_periods_report_no_gaps_instead_of_guessing():
    out = compliance_summary([_t("FY25", "ok"), _t("FY27", "breach")])
    assert out["missing"] == [] and out["first_breach"] == "FY27"
