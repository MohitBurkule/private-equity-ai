"""iManage Work document management: one folder's documents, each downloaded as a file. Each item is cited to its
document URL, and its version is the document version, so a re-sync stores only documents that changed.
Token is a bearer token, used per request, never stored. The API shape is SYNTHETIC (see
deploy/mocks/wiremock/mappings/imanage.json) until iManage's documentation for the tenant is in hand:
  GET {base_url}/v1/folders/{folder}/documents -> {"items": [{"id", "name", "version"}]}
  GET {base_url}/v1/documents/{id}/content     -> the file bytes
"""
from __future__ import annotations

from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item


class IManage(Connector):
    name, label = "imanage", "iManage"

    def items(self, limit: int = 50):
        base = self.opts.get("base_url", "").rstrip("/")
        folder = self.opts.get("folder", "")
        if not base.startswith("https://") or not folder:
            raise ConnectorError("opts.base_url (https) and opts.folder are required")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            listing = self._get_json(f"{base}/v1/folders/{quote(folder, safe='')}/documents")["items"]
            docs = [(str(d["id"]), str(d["name"]), str(d["version"])) for d in listing[:limit]]
        except (KeyError, ValueError, TypeError) as e:
            raise ConnectorError(f"imanage response not in the expected shape: {e}") from e
        for doc_id, name, version in docs:
            data = self.http(f"{base}/v1/documents/{quote(doc_id, safe='')}/content", headers)
            yield Item(f"imanage:{doc_id}", name, data, f"{base}/v1/documents/{doc_id}", version)
