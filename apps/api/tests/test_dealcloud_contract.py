"""DealCloud adapter contract: the same rules every connector keeps, checked against a synthetic
DealCloud entrydata response (no real tenant)."""
import json

import pytest

from app.connectors.base import ConnectorError, Item
from app.connectors.crm import DealCloud

SITE = "acme.dealcloud.com"


def fake(rows):
    calls = []

    def http(url, headers):
        calls.append(url)
        assert url.startswith(f"https://{SITE}/api/rest/v4/data/entrydata/rows/")
        return json.dumps({"rows": rows}).encode()
    http.calls = calls
    return http


ROWS = [{"id": 7, "Name": "Atlas", "Stage": "IC", "EV": 900, "attributes": {"x": 1}}]


def test_contract_item_fields_and_stable_version():
    http = fake(ROWS)
    conn = DealCloud("tok", http, site=SITE, objects="Deals")
    (a,) = list(conn.items())
    (b,) = list(conn.items())
    assert isinstance(a, Item)
    assert a.external_id == "dealcloud:Deals"
    assert a.name == "dealcloud-Deals.csv"
    assert a.url == f"https://{SITE}/#/Deals"  # citation target is the object home, not the API
    assert a.version == b.version  # unchanged data keeps its version, so sync skips it
    assert a.data.splitlines()[0] == b"id,Name,Stage,EV"  # nested attributes dropped


def test_contract_refuses_missing_token_foreign_host_and_missing_objects():
    with pytest.raises(ConnectorError):
        DealCloud("", fake(ROWS), site=SITE, objects="Deals")
    with pytest.raises(ConnectorError, match="dealcloud"):
        list(DealCloud("tok", fake(ROWS), site="evil.example.com", objects="Deals").items())
    with pytest.raises(ConnectorError, match="entry type"):
        list(DealCloud("tok", fake(ROWS), site=SITE).items())


def test_contract_empty_object_yields_nothing():
    assert list(DealCloud("tok", fake([]), site=SITE, objects="Deals").items()) == []
