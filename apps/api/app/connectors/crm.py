"""CRM connectors. Each object type (deals, companies, contacts) becomes one CSV document, so rows keep
the `row N: Header=value` form the fact gate cites. Granularity is the object list, not the record: the
source URL points at the object's home in the CRM. Version is a content hash, so unchanged data is skipped."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from collections.abc import Iterator
from typing import ClassVar

from app.connectors.base import Connector, ConnectorError, Item


def to_csv(rows: list[dict]) -> bytes:
    """Scalar fields only (nested objects and lists are dropped, never stringified into noise)."""
    cols: list[str] = []
    for r in rows:
        for k, v in r.items():
            if k != "attributes" and not isinstance(v, dict | list) and k not in cols:
                cols.append(k)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return buf.getvalue().encode()


class CrmConnector(Connector):
    objects: tuple[str, ...] = ()

    def fetch_rows(self, obj: str, limit: int) -> list[dict]:
        raise NotImplementedError

    def home_url(self, obj: str) -> str:
        raise NotImplementedError

    def items(self, limit: int = 50) -> Iterator[Item]:
        for obj in self.opts.get("objects", ",".join(self.objects)).split(","):
            obj = obj.strip()
            rows = self.fetch_rows(obj, limit)
            if not rows:
                continue
            data = to_csv(rows)
            yield Item(f"{self.name}:{obj}", f"{self.name}-{obj}.csv", data, self.home_url(obj),
                       hashlib.sha256(data).hexdigest()[:16])


class Salesforce(CrmConnector):
    """opts: instance_url (required, e.g. https://acme.my.salesforce.com), objects (default Account,Opportunity,Contact)."""
    name, label = "salesforce", "Salesforce"
    objects = ("Account", "Opportunity", "Contact")
    FIELDS: ClassVar[dict[str, str]] = {"Account": "Id,Name,Industry,AnnualRevenue,NumberOfEmployees,BillingCountry",
              "Opportunity": "Id,Name,StageName,Amount,CloseDate,AccountId",
              "Contact": "Id,Name,Title,AccountId,Email"}

    def _base(self) -> str:
        u = self.opts.get("instance_url", "").rstrip("/")
        if not u.startswith("https://") or not u.endswith((".salesforce.com", ".force.com")):
            raise ConnectorError("instance_url must be an https salesforce.com / force.com host")
        return u

    def fetch_rows(self, obj, limit):
        if obj not in self.FIELDS:
            raise ConnectorError(f"unsupported Salesforce object {obj}")
        from urllib.parse import quote
        q = quote(f"SELECT {self.FIELDS[obj]} FROM {obj} LIMIT {limit}")
        return self._get_json(f"{self._base()}/services/data/v60.0/query?q={q}").get("records", [])

    def home_url(self, obj):
        return f"{self._base()}/lightning/o/{obj}/list"

    def fetch_stages(self, limit: int) -> list[dict]:
        from urllib.parse import quote
        q = quote(f"SELECT Id,Name,StageName FROM Opportunity LIMIT {limit}")
        records = self._get_json(f"{self._base()}/services/data/v60.0/query?q={q}").get("records", [])
        return [{"id": r["Id"], "name": r.get("Name") or "", "stage": r.get("StageName") or ""} for r in records]

    def push_stage(self, ext_id: str, stage: str) -> None:
        from urllib.parse import quote
        url = f"{self._base()}/services/data/v60.0/sobjects/Opportunity/{quote(ext_id, safe='')}"
        self.http(url, {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                        "X-Method": "PATCH", "X-Post-Body": json.dumps({"StageName": stage})})


class HubSpot(CrmConnector):
    name, label = "hubspot", "HubSpot"
    objects = ("companies", "deals", "contacts")

    def fetch_rows(self, obj, limit):
        page = self._get_json(f"https://api.hubapi.com/crm/v3/objects/{obj}?limit={min(limit, 100)}")
        return [{"id": r["id"], **r.get("properties", {})} for r in page.get("results", [])]

    def home_url(self, obj):
        return f"https://app.hubspot.com/contacts/{self.opts.get('portal', '')}/objects/{obj}"


class Affinity(CrmConnector):
    """Affinity uses HTTP Basic with an empty user and the API key as password."""
    name, label = "affinity", "Affinity"
    objects = ("organizations", "persons", "opportunities")

    def _get_json(self, url):
        import json
        auth = base64.b64encode(f":{self.token}".encode()).decode()
        return json.loads(self.http(url, {"Authorization": f"Basic {auth}", "Accept": "application/json"}))

    def fetch_rows(self, obj, limit):
        page = self._get_json(f"https://api.affinity.co/{obj}?page_size={min(limit, 500)}")
        return page.get(obj) or page.get("data", []) if isinstance(page, dict) else page

    def home_url(self, obj):
        return f"https://app.affinity.co/{obj}"


class DealCloud(CrmConnector):
    """DealCloud (Intapp) is tenant-specific: opts site (e.g. acme.dealcloud.com) and objects (entry type
    api names, since every firm models its own). Data API v4 `entrydata/rows/{type}`."""
    name, label = "dealcloud", "DealCloud"

    def _site(self) -> str:
        s = self.opts.get("site", "")
        if not s.endswith(".dealcloud.com"):
            raise ConnectorError("opts.site must be a *.dealcloud.com host")
        return s

    def fetch_rows(self, obj, limit):
        page = self._get_json(f"https://{self._site()}/api/rest/v4/data/entrydata/rows/{obj}?limit={limit}")
        return page.get("rows", page if isinstance(page, list) else [])

    def home_url(self, obj):
        return f"https://{self._site()}/#/{obj}"

    def _stage_object(self) -> str:
        return self.opts.get("stage_object") or self.opts.get("objects", "").split(",")[0].strip()

    def fetch_stages(self, limit: int) -> list[dict]:
        """opts: stage_object (entry type api name), stage_field (default 'stage'), name_field (default 'name')."""
        obj, stage, name = self._stage_object(), self.opts.get("stage_field", "stage"), self.opts.get("name_field", "name")
        rows = self.fetch_rows(obj, limit)
        return [{"id": str(r["id"]), "name": str(r.get(name) or ""), "stage": str(r.get(stage) or "")} for r in rows]

    def push_stage(self, ext_id: str, stage: str) -> None:
        field = self.opts.get("stage_field", "stage")
        url = f"https://{self._site()}/api/rest/v4/data/entrydata/rows/{self._stage_object()}"
        self.http(url, {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                        "X-Method": "PUT", "X-Post-Body": json.dumps([{"id": ext_id, field: stage}])})

    def items(self, limit: int = 50):
        if not self.opts.get("objects"):
            raise ConnectorError("DealCloud needs opts.objects (your entry type names)")
        return super().items(limit)
