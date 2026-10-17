"""Calendar connectors against WireMock (open-source jar, Graph and Google stubs shaped like the real APIs),
plus the board-cadence watcher fed by a calendar sync. Stub-only tests need no jar."""
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import alerts
from app.connectors.calendar import GoogleCalendar, OutlookCalendar
from app.main import app
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
needs_jar = pytest.mark.skipif(not WireMock().available, reason="WIREMOCK_JAR not set")


@pytest.fixture(scope="module")
def wm():
    with WireMock() as w:
        yield w


@needs_jar
def test_outlook_calendar_through_wiremock(wm):
    http = rewrite_http({"https://graph.microsoft.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/v1.0/me/calendarView"}, body=json.dumps({"value": [
        {"id": "E1", "subject": "Acme board meeting Q3", "start": {"dateTime": "2026-10-01T09:00:00.0000000"},
         "webLink": "https://outlook.office.com/calendar/item/E1"}]}), headers={"Content-Type": "application/json"})
    conn = OutlookCalendar("tok", http)
    (item,) = list(conn.items(limit=10))
    assert b"Acme board meeting Q3" in item.data and item.name == "outlook-calendar.csv"
    assert conn.last_events == [{"external_id": "E1", "title": "Acme board meeting Q3",
                                 "starts_at": "2026-10-01T09:00:00.0000000",
                                 "url": "https://outlook.office.com/calendar/item/E1"}]


@needs_jar
def test_google_calendar_through_wiremock(wm):
    http = rewrite_http({"https://www.googleapis.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/calendar/v3/calendars/primary/events"}, body=json.dumps({"items": [
        {"id": "g1", "summary": "Board meeting - Acme", "start": {"date": "2026-09-15"},
         "htmlLink": "https://www.google.com/calendar/event?eid=g1"}]}), headers={"Content-Type": "application/json"})
    conn = GoogleCalendar("tok", http)
    (item,) = list(conn.items(limit=10))
    assert b"Board meeting - Acme" in item.data
    assert conn.last_events[0]["starts_at"] == "2026-09-15"


def test_window_bounds_are_checked():
    from app.connectors.base import ConnectorError
    from app.connectors.calendar import _window
    with pytest.raises(ConnectorError):
        _window({"days_ahead": "9999"})


def _calendar_http(events):
    def http(url, headers):
        assert headers["Authorization"] == "Bearer tok"
        return json.dumps({"value": events}).encode()
    return http


def test_board_cadence_flags_overdue_board_meetings_only(monkeypatch):
    events = [
        {"id": "b1", "subject": "Acme board meeting", "start": {"dateTime": "2020-01-10T09:00:00"}, "webLink": "u1"},
        {"id": "s1", "subject": "Acme sales call", "start": {"dateTime": "2026-10-01T09:00:00"}, "webLink": "u2"},
        {"id": "b2", "subject": "Beta board meeting", "start": {"dateTime": "2026-10-02T09:00:00"}, "webLink": "u3"},
    ]
    monkeypatch.setattr(m, "CONNECTOR_HTTP", _calendar_http(events))
    rule = SimpleNamespace(value="board meets quarterly", document_id=3, page=1, quote="board meets quarterly")
    monkeypatch.setattr(alerts.fk, "newest_accepted",
                        lambda db, t, key: rule if key == "board_meeting_cadence" else None)
    h = new_tenant(c, "board-cadence")
    c.post("/portfolio/companies", json={"name": "Acme"}, headers=h)
    c.post("/portfolio/companies", json={"name": "Beta"}, headers=h)
    r = c.post("/connectors/outlook-calendar/sync", json={"token": "tok"}, headers=h)
    assert r.status_code == 200, r.text
    c.post("/alerts/scan", headers=h)
    board = [a for a in c.get("/alerts", headers=h).json() if a["kind"] == "board"]
    days = (datetime.now(UTC).date() - date(2020, 1, 10)).days
    assert [a["title"] for a in board] == [f"Acme: no board meeting for {days} days (firm cadence 92 days)"]
    assert "board meets quarterly" in board[0]["detail"]
