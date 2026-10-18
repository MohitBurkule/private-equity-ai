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


# Room API (listing, permissions). Off unless DATAROOM_API=1: the endpoint paths and JSON shape below are NOT
# verified against either vendor's documentation, so they are a mock contract for tests and offline demos until a
# real account confirms them. The export path above is unaffected.
API_BASE = {"intralinks": "https://api.intralinks.com", "datasite": "https://api.datasite.com"}


class DataRoomApi(DataRoomExport):
    """opts: room_id (required), vendor is taken from the class name. Lists files and permissions for one room."""

    def _api_on(self) -> None:
        import os
        if os.environ.get("DATAROOM_API") != "1":
            raise ConnectorError("data room API is off (set DATAROOM_API=1; endpoint shape unverified)")

    def _get_json(self, path: str):
        import json
        base = API_BASE[self.name]
        return json.loads(self.http(f"{base}{path}", {"Authorization": f"Bearer {self.token}",
                                                      "Accept": "application/json"}))

    def list_files(self, limit: int = 200) -> list[dict]:
        self._api_on()
        room = self.opts.get("room_id", "")
        if not room:
            raise ConnectorError("room_id is required")
        page = self._get_json(f"/rooms/{room}/files?limit={min(limit, 500)}")
        return [{"path": f.get("path") or f.get("name", ""), "size": int(f.get("size") or 0),
                 "modified": f.get("modified") or ""} for f in page.get("files", [])]

    def permissions(self) -> list[dict]:
        self._api_on()
        room = self.opts.get("room_id", "")
        if not room:
            raise ConnectorError("room_id is required")
        page = self._get_json(f"/rooms/{room}/permissions")
        return [{"user": p.get("user", ""), "role": p.get("role", "")} for p in page.get("permissions", [])]


class IntralinksApi(DataRoomApi):
    name, label = "intralinks", "Intralinks room API"


class DatasiteApi(DataRoomApi):
    name, label = "datasite", "Datasite room API"
