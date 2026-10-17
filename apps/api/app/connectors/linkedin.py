"""LinkedIn via the member's own data export (Settings > Get a copy of your data). This is the only route
used: LinkedIn's API does not offer connection or message access to a firm, and scraping breaks its terms.
The export is a zip of CSVs; each CSV becomes one document, so rows cite as `Header=value`.
Source URL is LinkedIn's home, since the export has no per-record links."""
from __future__ import annotations

import hashlib
import io
import zipfile

from app.connectors.base import Connector, ConnectorError, Item

MAX_MEMBER_BYTES = 20 * 1024 * 1024


class LinkedInExport(Connector):
    name, label = "linkedin", "LinkedIn data export"

    def __init__(self, data: bytes):  # no token or HTTP: the file is the input
        self.data, self.token, self.http, self.opts = data, "export", None, {}

    def items(self, limit: int = 50):
        try:
            zf = zipfile.ZipFile(io.BytesIO(self.data))
        except zipfile.BadZipFile as e:
            raise ConnectorError("LinkedIn export must be the zip file LinkedIn provides") from e
        n = 0
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                raise ConnectorError(f"{info.filename} is larger than {MAX_MEMBER_BYTES} bytes")
            if n >= limit:
                return
            payload = zf.read(info)
            base = info.filename.rsplit("/", 1)[-1]
            yield Item(f"linkedin:{base}", f"linkedin-{base}", payload, "https://www.linkedin.com/",
                       hashlib.sha256(payload).hexdigest()[:16])
            n += 1
