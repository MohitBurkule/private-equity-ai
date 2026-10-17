"""Catalogue of every integration the product targets and how far each one is. Honest status:
`live` = code path exists and replays against recorded-shape fixtures (no real-credential run yet);
`planned` = not built. Keep in step with design/INTEGRATIONS.md."""
from __future__ import annotations

from app.connectors.base import Connector
from app.connectors.crm import Affinity, DealCloud, HubSpot, Salesforce
from app.connectors.dataroom import Datasite, Intralinks
from app.connectors.files import Box, Dropbox, GoogleDrive
from app.connectors.gmail import Gmail
from app.connectors.graph import OneDriveSharePoint, Outlook
from app.connectors.gsheets import GoogleSheets
from app.connectors.imap import Imap
from app.connectors.mailpit import Mailpit
from app.connectors.slack import Slack

IMPLEMENTED: dict[str, type[Connector]] = {c.name: c for c in (Gmail, Outlook, OneDriveSharePoint, GoogleDrive, Box, Dropbox, GoogleSheets, Imap, Mailpit,
                                                                     Salesforce, HubSpot, Affinity, DealCloud, Slack, Intralinks, Datasite)}

CATALOG = [  # (name, label, category, auth)
    ("gmail", "Gmail", "email", "OAuth2"), ("mailpit", "Mailpit (dev inbox)", "email", "none, local only"), ("imap", "Any IMAP mailbox", "email", "password / app password"), ("outlook", "Outlook / Exchange", "email", "OAuth2 (Graph)"),
    ("gdrive", "Google Drive", "files", "OAuth2"), ("gsheets", "Google Sheets (two-way)", "files", "OAuth2"), ("sharepoint", "SharePoint / OneDrive", "files", "OAuth2 (Graph)"),
    ("box", "Box", "files", "OAuth2"), ("dropbox", "Dropbox", "files", "OAuth2"),
    ("salesforce", "Salesforce", "crm", "OAuth2"), ("dealcloud", "DealCloud", "crm", "OAuth2 client credentials"),
    ("affinity", "Affinity", "crm", "API key"), ("hubspot", "HubSpot", "crm", "OAuth2 / private app token"),
    ("slack", "Slack", "chat", "OAuth2"), ("intralinks", "Intralinks", "dataroom", "bulk export URL"),
    ("datasite", "Datasite", "dataroom", "bulk export URL"),
    ("capiq", "S&P Capital IQ", "market data", "licensed API"), ("factset", "FactSet", "market data", "licensed API"),
    ("pitchbook", "PitchBook", "market data", "licensed API / export"),
    ("linkedin", "LinkedIn", "people", "member data export (upload)"),
]


IMPORTS = {"linkedin"}  # upload-only sources: no token sync, see connectors/linkedin.py


def catalog() -> list[dict]:
    return [{"name": n, "label": lbl, "category": cat, "auth": auth,
             "status": "live" if n in IMPLEMENTED or n in IMPORTS else "planned"} for n, lbl, cat, auth in CATALOG]
