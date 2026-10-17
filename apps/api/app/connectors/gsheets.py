"""Google Sheets, both ways. Pull: each tab becomes one CSV document, so edits made in the sheet are
ingested and cite the sheet. Push: verified facts are written to a tab (values:batchUpdate), so the sheet
shows the same numbers the app holds. Tokens are per call, as with every connector."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item

API = "https://sheets.googleapis.com/v4/spreadsheets"


def rows_csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


class GoogleSheets(Connector):
    """opts: spreadsheet=<id from the sheet URL> (required), range=<tab or A1 range> (default Sheet1)."""
    name, label = "gsheets", "Google Sheets"

    def _sheet(self) -> str:
        sid = self.opts.get("spreadsheet", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", sid):
            raise ConnectorError("opts.spreadsheet must be a spreadsheet id")
        return sid

    def _range(self) -> str:
        return self.opts.get("range", "Sheet1") or "Sheet1"

    def items(self, limit: int = 50):
        sid, rng = self._sheet(), self._range()
        values = self._get_json(f"{API}/{sid}/values/{quote(rng)}").get("values", [])
        if not values:
            return
        data = rows_csv(values)
        yield Item(f"gsheets:{sid}:{rng}", f"gsheets-{re.sub(r'[^A-Za-z0-9_-]', '-', rng)}.csv", data,
                   f"https://docs.google.com/spreadsheets/d/{sid}/edit",
                   hashlib.sha256(data).hexdigest()[:16])

    def push(self, rows: list[list]) -> int:
        """Overwrite the range's top-left cells with rows (header first). Returns updated cell count."""
        body = json.dumps({"valueInputOption": "RAW", "data": [{"range": self._range(), "values": rows}]})
        raw = self.http(f"{API}/{self._sheet()}/values:batchUpdate",
                        {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                         "X-Post-Body": body})
        return int(json.loads(raw).get("totalUpdatedCells", 0))
