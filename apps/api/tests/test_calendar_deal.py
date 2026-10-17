"""Calendar meetings name a deal: tagged by its name or alias when exactly one deal matches the title, listed on
the deal's meetings view, and hidden from keys that cannot see the deal."""
from fastapi.testclient import TestClient

import app.main as m
from app.calendar_events import record_events
from app.main import app
from app.rls import bind_tenant
from tests.helpers import new_tenant_id

c = TestClient(app)


def _record(tid: str, events: list[dict]) -> None:
    with m.SessionLocal() as db:
        bind_tenant(db, tid)
        record_events(db, tid, "outlook", events)


def test_meeting_is_tagged_by_deal_alias_and_listed_for_the_deal():
    h, tid = new_tenant_id(c, "cal-deal")
    assert c.post("/deals", headers=h, json={"name": "Atlas", "aliases": ["Project Blue"]}).status_code == 201
    assert c.post("/deals", headers=h, json={"name": "Borealis"}).status_code == 201
    _record(tid, [
        {"external_id": "1", "title": "Project Blue IC prep", "starts_at": "2026-11-02T10:00", "url": "u1"},
        {"external_id": "2", "title": "Atlas board meeting", "starts_at": "2026-10-20T09:00", "url": "u2"},
        {"external_id": "3", "title": "Atlas and Borealis sync", "starts_at": "2026-10-21", "url": "u3"},
        {"external_id": "4", "title": "Team lunch", "starts_at": "2026-10-22", "url": "u4"},
    ])
    out = c.get("/deals/Atlas/meetings", headers=h).json()["meetings"]
    assert [(x["title"], x["board"]) for x in out] == [("Atlas board meeting", True), ("Project Blue IC prep", False)]


def test_meetings_of_an_unknown_deal_are_404():
    h, _ = new_tenant_id(c, "cal-missing")
    assert c.get("/deals/Nope/meetings", headers=h).status_code == 404


def test_mnpi_deal_meetings_are_hidden_from_uncleared_keys():
    h, tid = new_tenant_id(c, "cal-mnpi")
    assert c.post("/deals", headers=h, json={"name": "Secret", "mnpi": True}).status_code == 201
    _record(tid, [{"external_id": "9", "title": "Secret review", "starts_at": "2026-10-30", "url": "u9"}])
    assert c.get("/deals/Secret/meetings", headers=h).json()["meetings"][0]["title"] == "Secret review"
    k = c.post(f"/admin/tenants/{tid}/keys", json={"role": "associate", "deals": ["Other"]},
               headers={"X-Admin-Token": "test-admin"}).json()
    scoped = {"Authorization": f"Bearer {k['api_key']}"}
    assert c.get("/deals/Secret/meetings", headers=scoped).status_code == 404
