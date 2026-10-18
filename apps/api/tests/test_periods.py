"""Period labels: known ones pass with no warning, odd ones get a warning and are still stored. SYNTHETIC figures."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.periods import period_warning
from tests.helpers import new_tenant
from tests.test_acl import up

c = TestClient(app)


@pytest.mark.parametrize("p", ["2026", "FY24", "FY2024", "2026-09", "2026-06-30", "2026-Q2", "2026Q2",
                               "FY2026Q2", "LTM", "NTM"])
def test_known_periods_have_no_warning(p):
    assert period_warning(p) is None


@pytest.mark.parametrize("p", ["per agreement", "Q1", "FY", "2026-13", "p"])
def test_unknown_periods_warn(p):
    assert "not a recognised label" in period_warning(p)


def test_fact_with_odd_period_is_stored_and_carries_a_warning():
    h = new_tenant(c, "period-warn")
    doc = up(c, h, "Synth revenue 1,234").json()["id"]
    r = c.post("/facts", headers=h, json={"entity": "Synth", "metric": "revenue", "period": "Q1", "value": "1234",
                                          "unit": "USD", "document_id": doc, "page": 1,
                                          "quote": "Sheet!B1: 1,234"})
    assert r.status_code == 201, r.text
    assert "not a recognised label" in r.json()["warning"]
