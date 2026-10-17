"""Calendar connectors: meetings in a window (default: 365 days back, 90 days ahead) become one cited CSV per
calendar, and each event is also recorded as a structured row (app/calendar_events.py) so the board-cadence
watcher can read meeting dates. Outlook reads Graph calendarView; Google reads the primary calendar."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item
from app.connectors.crm import to_csv

GRAPH = "https://graph.microsoft.com/v1.0"
GCAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _window(opts: dict[str, str]) -> tuple[str, str]:
    back, ahead = int(opts.get("days_back", "365")), int(opts.get("days_ahead", "90"))
    if not (0 <= back <= 3650 and 0 <= ahead <= 366):
        raise ConnectorError("days_back must be 0..3650 and days_ahead 0..366")
    now = datetime.now(UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return quote((now - timedelta(days=back)).strftime(fmt)), quote((now + timedelta(days=ahead)).strftime(fmt))


class CalendarConnector(Connector):
    home_url = ""
    last_events: list[dict]

    def fetch_events(self, limit: int) -> list[dict]:
        """Each event: external_id, title, starts_at (ISO string), url."""
        raise NotImplementedError

    def items(self, limit: int = 50):
        self.last_events = self.fetch_events(limit)
        if not self.last_events:
            return
        data = to_csv([{"title": e["title"], "starts_at": e["starts_at"], "url": e["url"]} for e in self.last_events])
        yield Item(f"{self.name}:window", f"{self.name}.csv", data, self.home_url,
                   hashlib.sha256(data).hexdigest()[:16])


class OutlookCalendar(CalendarConnector):
    name, label = "outlook-calendar", "Outlook calendar"
    home_url = "https://outlook.office.com/calendar/"

    def fetch_events(self, limit):
        start, end = _window(self.opts)
        page = self._get_json(f"{GRAPH}/me/calendarView?startDateTime={start}&endDateTime={end}"
                              f"&$top={min(limit, 100)}&$select=id,subject,start,webLink")
        return [{"external_id": e["id"], "title": e.get("subject", ""),
                 "starts_at": e.get("start", {}).get("dateTime", ""), "url": e.get("webLink", "")}
                for e in page.get("value", [])][:limit]


class GoogleCalendar(CalendarConnector):
    name, label = "google-calendar", "Google Calendar"
    home_url = "https://calendar.google.com/calendar/"

    def fetch_events(self, limit):
        start, end = _window(self.opts)
        page = self._get_json(f"{GCAL}?timeMin={start}&timeMax={end}&singleEvents=true"
                              f"&orderBy=startTime&maxResults={min(limit, 250)}")
        out = []
        for e in page.get("items", [])[:limit]:
            when = e.get("start", {})
            out.append({"external_id": e["id"], "title": e.get("summary", ""),
                        "starts_at": when.get("dateTime") or when.get("date", ""), "url": e.get("htmlLink", "")})
        return out
