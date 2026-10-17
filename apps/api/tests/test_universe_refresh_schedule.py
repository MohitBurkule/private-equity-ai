from fastapi.testclient import TestClient

from app import companies_house as ch_mod
from app import targets as tg_mod
from app import workflows as wf_mod
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def _fake_sec(cik):
    return ({"cik": int(cik), "name": "Refreshed Inc", "sic": "7372", "sicDescription": "Services",
             "addresses": {"business": {"isForeignLocation": False, "stateOrCountry": "CA"}}}, None)


def test_scheduled_refresh_runs_when_due_and_reports_counts(monkeypatch):
    monkeypatch.setattr(wf_mod, "smtp_mailer", lambda: None)
    monkeypatch.setattr(tg_mod, "live_sec_fetch", _fake_sec)
    monkeypatch.setattr(ch_mod, "fetch_company", lambda number, api_key=None: None)
    h = new_tenant(c, "refresh-sched")
    c.post("/targets/import/sec", headers=h, json={
        "submissions": {"cik": 320193, "name": "Old Name", "sic": "7372", "sicDescription": "Services",
                        "addresses": {"business": {"isForeignLocation": False, "stateOrCountry": "CA"}}},
        "companyfacts": None})
    w = c.post("/workflows", headers=h, json={"name": "nightly refresh", "kind": "universe_refresh",
                                              "every_days": 1, "params": {"limit": 50}}).json()
    runs = {r["id"]: r["status"] for r in c.post("/workflows/run-due", headers=h).json()}
    assert runs == {w["id"]: "ok"}
    last = c.get(f"/workflows/{w['id']}/last", headers=h).json()
    assert "Universe refresh: 1 of 1 refreshed, 0 failed, 0 dissolved." in last["last_result"]
    assert c.post("/workflows/run-due", headers=h).json() == []  # waits for its next run

