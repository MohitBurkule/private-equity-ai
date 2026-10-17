"""LBO base rate from a cited macro series. SYNTHETIC FRED body (no live key or CSV in the build)."""
from fastapi.testclient import TestClient

from app.main import app, get_market_fetch
from tests.helpers import new_tenant

c = TestClient(app)
CSV = b"observation_date,SOFR\n2026-10-14,3.60\n2026-10-15,.\n2026-10-16,3.62\n"


def _inputs(rate_spec):
    cite = {"document_id": "d1", "page": 1, "quote": "x"}
    base = {
        "ebitda": {"value": 100, "source": cite},
        "entry_multiple": {"value": 8, "source": cite},
        "exit_multiple": {"value": 8, "source": cite},
        "leverage": {"value": 5, "source": cite},
        "tax_rate": {"value": 25, "source": cite},
        "cash_conversion": {"value": 80, "source": cite},
        "fees_pct": {"value": 2, "source": cite},
        "years": {"value": 5, "source": cite},
    }
    base["interest_rate"] = rate_spec
    return {"inputs": base}


def _run(rate_spec):
    app.dependency_overrides[get_market_fetch] = lambda: (lambda u, h: CSV)
    try:
        h = new_tenant(c, "lbo-rate")
        return c.post("/lbo/returns", json=_inputs(rate_spec), headers=h)
    finally:
        app.dependency_overrides.pop(get_market_fetch, None)


def test_interest_rate_from_cited_series_plus_margin():
    r = _run({"rate_series": {"series": "SOFR", "margin_pct": "4.25"}})
    assert r.status_code == 200, r.text
    rates = r.json()["base_rates"]
    assert [x["input"] for x in rates] == ["interest_rate"]
    assert rates[0]["series"] == "SOFR" and rates[0]["as_of"] == "2026-10-16" and rates[0]["base_value"] == "3.62"
    assert rates[0]["value"] == "7.87"  # 3.62 + 4.25


def test_missing_series_value_is_refused_not_guessed():
    body = b"observation_date,SOFR\n2026-10-16,.\n"
    app.dependency_overrides[get_market_fetch] = lambda: (lambda u, h: body)
    try:
        h = new_tenant(c, "lbo-rate-miss")
        r = c.post("/lbo/returns", json=_inputs({"rate_series": {"series": "SOFR", "margin_pct": "4"}}), headers=h)
    finally:
        app.dependency_overrides.pop(get_market_fetch, None)
    assert r.status_code == 422 and "interest_rate" in r.text
