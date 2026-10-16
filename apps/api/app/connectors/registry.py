"""Catalogue of every integration the product targets and how far each one is. Honest status:
`live` = code path exists and replays against recorded-shape fixtures (no real-credential run yet);
`planned` = not built. Keep in step with design/INTEGRATIONS.md."""
from __future__ import annotations

from app.connectors.base import Connector
from app.connectors.gmail import Gmail
from app.connectors.graph import OneDriveSharePoint, Outlook

IMPLEMENTED: dict[str, type[Connector]] = {c.name: c for c in (Gmail, Outlook, OneDriveSharePoint)}

CATALOG = [  # (name, label, category, auth)
    ("gmail", "Gmail", "email", "OAuth2"), ("outlook", "Outlook / Exchange", "email", "OAuth2 (Graph)"),
    ("gdrive", "Google Drive / Sheets", "files", "OAuth2"), ("sharepoint", "SharePoint / OneDrive", "files", "OAuth2 (Graph)"),
    ("box", "Box", "files", "OAuth2"), ("dropbox", "Dropbox", "files", "OAuth2"),
    ("salesforce", "Salesforce", "crm", "OAuth2"), ("dealcloud", "DealCloud", "crm", "OAuth2 client credentials"),
    ("affinity", "Affinity", "crm", "API key"), ("hubspot", "HubSpot", "crm", "OAuth2 / private app token"),
    ("slack", "Slack", "chat", "OAuth2"), ("intralinks", "Intralinks", "dataroom", "OAuth2 / export"),
    ("datasite", "Datasite", "dataroom", "export / API"),
    ("capiq", "S&P Capital IQ", "market data", "licensed API"), ("factset", "FactSet", "market data", "licensed API"),
    ("pitchbook", "PitchBook", "market data", "licensed API / export"),
    ("linkedin", "LinkedIn", "people", "official API only"),
]


def catalog() -> list[dict]:
    return [{"name": n, "label": lbl, "category": cat, "auth": auth,
             "status": "live" if n in IMPLEMENTED else "planned"} for n, lbl, cat, auth in CATALOG]
