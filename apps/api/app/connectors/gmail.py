"""Gmail: messages as raw RFC822, so the existing .eml parser extracts body and attachments."""
from __future__ import annotations

import base64
from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item

API = "https://gmail.googleapis.com/gmail/v1/users/me"


class Gmail(Connector):
    name, label = "gmail", "Gmail"

    def items(self, limit: int = 50):
        q = quote(self.opts.get("query", ""))  # e.g. "label:project-atlas"; empty = whole mailbox
        token, n = "", 0
        while n < limit:
            page = self._get_json(f"{API}/messages?maxResults={min(100, limit - n)}&q={q}"
                                  + (f"&pageToken={token}" if token else ""))
            for m in page.get("messages", []):
                if n >= limit:
                    return
                msg = self._get_json(f"{API}/messages/{m['id']}?format=raw")
                raw = msg.get("raw")
                if not raw:
                    raise ConnectorError(f"message {m['id']} has no raw body")
                data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
                yield Item(m["id"], f"gmail-{m['id']}.eml", data,
                           f"https://mail.google.com/mail/u/0/#all/{m['id']}", str(msg.get("internalDate", "")))
                n += 1
            token = page.get("nextPageToken", "")
            if not token:
                return
