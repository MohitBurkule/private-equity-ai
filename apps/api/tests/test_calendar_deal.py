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


def _notes(h: dict, deal: str) -> list[dict]:
    return c.get(f"/deals/{deal}/notes", headers=h).json()


def test_meeting_body_becomes_a_cited_deal_note_that_follows_the_event():
    h, tid = new_tenant_id(c, "cal-notes")
    assert c.post("/deals", headers=h, json={"name": "Atlas"}).status_code == 201
    _record(tid, [{"external_id": "7", "title": "Atlas management call", "starts_at": "2026-10-19T14:00",
                   "url": "https://cal/7", "body": "Churn fell to 4%. Capex guide unchanged."}])
    (note,) = _notes(h, "Atlas")
    assert note["author"] == "calendar:outlook" and note["source_url"] == "https://cal/7"
    assert "Churn fell to 4%" in note["body"] and note["body"].startswith("Meeting 2026-10-19: Atlas management call")
    _record(tid, [{"external_id": "7", "title": "Atlas management call", "starts_at": "2026-10-19T14:00",
                   "url": "https://cal/7", "body": "Churn fell to 4%. Capex guide cut."}])
    (again,) = _notes(h, "Atlas")  # re-sync updates the same note, never a second one
    assert again["id"] == note["id"] and "Capex guide cut" in again["body"]


def test_meeting_without_text_or_deal_makes_no_note():
    h, tid = new_tenant_id(c, "cal-nonote")
    assert c.post("/deals", headers=h, json={"name": "Atlas"}).status_code == 201
    _record(tid, [{"external_id": "8", "title": "Atlas call", "starts_at": "2026-10-19", "url": "u8", "body": ""},
                  {"external_id": "9", "title": "Team lunch", "starts_at": "2026-10-19", "url": "u9", "body": "food"}])
    assert _notes(h, "Atlas") == []


def test_new_alias_and_new_deal_retag_meetings_already_stored():
    h, tid = new_tenant_id(c, "cal-retag")
    assert c.post("/deals", headers=h, json={"name": "Atlas"}).status_code == 201
    _record(tid, [{"external_id": "5", "title": "Project Blue steering", "starts_at": "2026-10-23",
                   "url": "u5", "body": "Agenda items."}])
    assert _notes(h, "Atlas") == []
    assert c.patch("/deals/Atlas", headers=h, json={"aliases": ["Project Blue"]}).status_code == 200
    assert [n["source_url"] for n in _notes(h, "Atlas")] == ["u5"]
    assert c.post("/deals", headers=h, json={"name": "Project Blue"}).status_code == 201
    # "Project Blue" now names two deals (Atlas by alias, and itself), so the meeting is untagged for both
    assert c.get("/deals/Project Blue/meetings", headers=h).json()["meetings"] == []
    assert _notes(h, "Atlas") == []
