"""Intralinks / Datasite data rooms via their bulk-export archive. The archive is a zip of the room's
folder tree, so ingestion reuses the existing archive path: each file keeps its folder prefix, and
encrypted or junk entries are reported as skipped rather than silently dropped.

Only the export URL is needed. It must be on the vendor's own domain, so a token never leaves for an
arbitrary host. Room API access (listing, permissions) is not implemented here."""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from app.connectors.base import Connector, ConnectorError, Item

ALLOWED_SUFFIXES = (".intralinks.com", ".datasite.com")


class DataRoomExport(Connector):
    """opts: export_url (required, https on intralinks.com or datasite.com), room (label used in the citation)."""
    name, label = "dataroom", "Intralinks / Datasite export"

    def items(self, limit: int = 50):
        url = self.opts.get("export_url", "")
        host = urlparse(url).hostname or ""
        if urlparse(url).scheme != "https" or not any(host.endswith(s) for s in ALLOWED_SUFFIXES):
            raise ConnectorError("export_url must be https on intralinks.com or datasite.com")
        data = self.http(url, {"Authorization": f"Bearer {self.token}"})
        if data[:2] != b"PK":
            raise ConnectorError("export is not a zip archive")
        room = self.opts.get("room", host)
        yield Item(hashlib.sha256(url.encode()).hexdigest()[:24], f"{room}.zip", data,
                   f"https://{host}/", hashlib.sha256(data).hexdigest()[:16])


class Intralinks(DataRoomExport):
    name, label = "intralinks", "Intralinks"


class Datasite(DataRoomExport):
    name, label = "datasite", "Datasite"
