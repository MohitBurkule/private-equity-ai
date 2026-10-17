"""Catalogue of every integration the product targets and how far each one is. Honest status:
`live` = code path exists and replays against recorded-shape fixtures (no real-credential run yet);
`planned` = not built. Keep in step with design/INTEGRATIONS.md."""
from __future__ import annotations

from app.connectors import oauth
from app.connectors.base import Connector
from app.connectors.calendar import GoogleCalendar, OutlookCalendar
from app.connectors.crm import Affinity, DealCloud, HubSpot, Salesforce
from app.connectors.dataroom import Datasite, Intralinks
from app.connectors.files import Box, Dropbox, GoogleDrive
from app.connectors.gmail import Gmail
from app.connectors.graph import OneDriveSharePoint, Outlook
from app.connectors.gsheets import GoogleSheets
from app.connectors.imap import Imap
from app.connectors.mailpit import Mailpit
from app.connectors.oauth import OAuthError
from app.connectors.s3 import S3Source
from app.connectors.sftp import SftpSource
from app.connectors.slack import Slack

IMPLEMENTED: dict[str, type[Connector]] = {c.name: c for c in (Gmail, Outlook, OneDriveSharePoint, GoogleDrive, Box, Dropbox, GoogleSheets, Imap, Mailpit,
                                                                     Salesforce, HubSpot, Affinity, DealCloud, Slack, Intralinks, Datasite, S3Source, SftpSource,
                                                                     OutlookCalendar, GoogleCalendar)}

CATALOG = [  # (name, label, category, auth)
    ("outlook-calendar", "Outlook calendar", "calendar", "OAuth2 (Graph)"), ("google-calendar", "Google Calendar", "calendar", "OAuth2"),
    ("gmail", "Gmail", "email", "OAuth2"), ("mailpit", "Mailpit (dev inbox)", "email", "none, local only"), ("imap", "Any IMAP mailbox", "email", "password / app password"), ("outlook", "Outlook / Exchange", "email", "OAuth2 (Graph)"),
    ("gdrive", "Google Drive", "files", "OAuth2"), ("gsheets", "Google Sheets (two-way)", "files", "OAuth2"), ("sharepoint", "SharePoint / OneDrive", "files", "OAuth2 (Graph)"),
    ("box", "Box", "files", "OAuth2"), ("dropbox", "Dropbox", "files", "OAuth2"),
    ("salesforce", "Salesforce", "crm", "OAuth2"), ("dealcloud", "DealCloud", "crm", "OAuth2 client credentials"),
    ("affinity", "Affinity", "crm", "API key"), ("hubspot", "HubSpot", "crm", "OAuth2 / private app token"),
    ("slack", "Slack", "chat", "OAuth2"), ("intralinks", "Intralinks", "dataroom", "bulk export URL"), ("s3", "S3 / object store", "dataroom", "access key"), ("sftp", "SFTP data room", "dataroom", "password + pinned host key"),
    ("datasite", "Datasite", "dataroom", "bulk export URL"),
    ("capiq", "S&P Capital IQ", "market data", "licensed API"), ("factset", "FactSet", "market data", "licensed API"),
    ("pitchbook", "PitchBook", "market data", "licensed API / export"),
    ("linkedin", "LinkedIn", "people", "member data export (upload)"),
    ("linkedin-enrichment", "LinkedIn enrichment", "people", "licence key"),
]


IMPORTS = {"linkedin"}  # upload-only sources: no token sync, see connectors/linkedin.py


def _oauth_ready(name: str) -> bool:
    try:
        oauth.config_for(name)
    except OAuthError:
        return False
    return True


def status(connected: set[str]) -> list[dict]:
    """Catalog plus each row's state: `connected` (saved connection, or no key needed), `needs_key`
    (built, but this deployment or tenant has no credentials for it yet) or `stubbed` (not built)."""
    out = []
    for c in catalog():
        n, auth = c["name"], c["auth"].lower()
        if c["status"] == "planned":
            state, detail = "stubbed", "not built yet"
        elif n in connected:
            state, detail = "connected", "saved connection"
        elif n in IMPORTS or auth.startswith("none"):
            state, detail = "connected", "no key needed"
        elif auth.startswith("oauth") and not _oauth_ready(n):
            state, detail = "needs_key", f"set OAUTH_{n.upper().replace('-', '_')}_CLIENT_ID, _CLIENT_SECRET, _AUTH_URL, _TOKEN_URL"
        else:
            state, detail = "needs_key", "add a key when you import"
        out.append({**c, "state": state, "detail": detail})
    return out


def catalog() -> list[dict]:
    return [{"name": n, "label": lbl, "category": cat, "auth": auth,
             "status": "live" if n in IMPLEMENTED or n in IMPORTS else "planned"} for n, lbl, cat, auth in CATALOG]


def connection_health(row) -> dict:
    """Last run of a saved connection: never run, ok, or error with the message it stored."""
    if row.last_run is None:
        return {"health": "never_run", "last_run": None, "last_status": None}
    state = "ok" if (row.last_status or "").startswith("ok") else "error"
    return {"health": state, "last_run": row.last_run, "last_status": row.last_status or ""}
