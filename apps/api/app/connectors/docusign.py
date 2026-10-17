"""DocuSign envelopes for one account. Each sync also stores the envelope list as a CSV document (cited by row), and
the stage sync (app/envelope_stage.py) reads the same list. Token is a bearer token, used per request, never stored.
The API shape is SYNTHETIC until the account's documentation is in hand:
  GET {base_url}/v2.1/accounts/{account}/envelopes?from_date=YYYY-MM-DD
      -> {"envelopes": [{"envelopeId", "status", "emailSubject", "completedDateTime"}]}
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item
from app.connectors.crm import to_csv

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
FIELDS = ("envelopeId", "status", "emailSubject", "completedDateTime")


class DocuSign(Connector):
    name, label = "docusign", "DocuSign"

    def envelopes(self) -> list[dict]:
        base = self.opts.get("base_url", "").rstrip("/")
        account = self.opts.get("account", "")
        since = self.opts.get("from_date", "")
        if not base.startswith("https://") or not account or not _DATE.fullmatch(since):
            raise ConnectorError("opts.base_url (https), opts.account and opts.from_date (YYYY-MM-DD) are required")
        url = f"{base}/v2.1/accounts/{quote(account, safe='')}/envelopes?from_date={since}"
        try:
            rows = json.loads(self.http(url, {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}))
            return [{k: str(e.get(k) or "") for k in FIELDS} for e in rows["envelopes"]]
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            raise ConnectorError(f"docusign response not in the expected shape: {e}") from e

    def items(self, limit: int = 50):
        envelopes = self.envelopes()[:limit]
        if not envelopes:
            return
        data = to_csv(envelopes)
        yield Item(hashlib.sha256(self.opts.get("account", "").encode()).hexdigest()[:24], "docusign-envelopes.csv",
                   data, f"{self.opts.get('base_url', '').rstrip('/')}/", hashlib.sha256(data).hexdigest()[:16])
