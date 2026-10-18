"""Reminders: a draft chaser for each portfolio company with nothing filed for the period. Nothing is sent."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def test_drafts_only_for_companies_with_no_submission():
    h = new_tenant(c, "kr1")
    a = c.post("/portfolio/companies", headers=h, json={"name": "Alpha Co"}).json()["id"]
    c.post("/portfolio/companies", headers=h, json={"name": "Beta Co"})
    out = c.get("/portfolio/submissions/reminders", headers=h, params={"period": "2026-09"}).json()
    names = [r["name"] for r in out]
    assert names == ["Alpha Co", "Beta Co"]
    assert all(r["text"].startswith("Please send your 2026-09 KPI pack") for r in out)
    assert a in {r["company_id"] for r in out}
