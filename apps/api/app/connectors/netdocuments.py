"""NetDocuments workspace documents: one workspace's documents, each downloaded as a file. Each item is cited to its
document URL, and its version is the document version, so a re-sync stores only documents that changed.
Token is a bearer token, used per request, never stored. The API shape is SYNTHETIC (see
deploy/mocks/wiremock/mappings/netdocuments.json) until NetDocuments' documentation for the tenant is in hand:
  GET {base_url}/v1/workspaces/{workspace}/documents -> {"items": [{"id", "name", "version"}]}
  GET {base_url}/v1/documents/{id}/content           -> the file bytes
"""
from __future__ import annotations

from urllib.parse import quote

from app.connectors.base import Connector, ConnectorError, Item


class NetDocuments(Connector):
    name, label = "netdocuments", "NetDocuments"

    def items(self, limit: int = 50):
        base = self.opts.get("base_url", "").rstrip("/")
        workspace = self.opts.get("workspace", "")
        if not base.startswith("https://") or not workspace:
            raise ConnectorError("opts.base_url (https) and opts.workspace are required")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            listing = self._get_json(f"{base}/v1/workspaces/{quote(workspace, safe='')}/documents")["items"]
            docs = [(str(d["id"]), str(d["name"]), str(d["version"])) for d in listing[:limit]]
        except (KeyError, ValueError, TypeError) as e:
            raise ConnectorError(f"netdocuments response not in the expected shape: {e}") from e
        for doc_id, name, version in docs:
            data = self.http(f"{base}/v1/documents/{quote(doc_id, safe='')}/content", headers)
            yield Item(f"netdocuments:{doc_id}", name, data, f"{base}/v1/documents/{doc_id}", version)
