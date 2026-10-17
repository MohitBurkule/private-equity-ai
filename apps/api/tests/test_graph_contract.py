"""Outlook and SharePoint adapter contract against a local fake of Microsoft Graph (synthetic data, no tenant).
Covers what the basic sync test does not: paging via @odata.nextLink, the limit, site drives, and bad responses."""
import json

import pytest

from app.connectors.base import ConnectorError, Item
from app.connectors.graph import G, OneDriveSharePoint, Outlook


def graph(routes):
    def http(url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if url not in routes:
            raise AssertionError(f"unrouted {url}")
        v = routes[url]
        return v if isinstance(v, bytes) else json.dumps(v).encode()
    return http


def test_outlook_follows_next_link_and_respects_limit():
    p2 = f"{G}/me/messages?page=2"
    http = graph({
        f"{G}/me/messages?$top=3&$select=id,webLink,lastModifiedDateTime": {
            "value": [{"id": "AAA111bbb222", "webLink": "https://outlook/1", "lastModifiedDateTime": "t1"},
                      {"id": "AAA333bbb444", "webLink": "https://outlook/2", "lastModifiedDateTime": "t2"}],
            "@odata.nextLink": p2},
        p2: {"value": [{"id": "AAA555bbb666", "webLink": "https://outlook/3", "lastModifiedDateTime": "t3"}]},
        f"{G}/me/messages/AAA111bbb222/$value": b"From: a@x\n\nbody1",
        f"{G}/me/messages/AAA333bbb444/$value": b"From: a@x\n\nbody2",
        f"{G}/me/messages/AAA555bbb666/$value": b"From: a@x\n\nbody3",
    })
    items = list(Outlook("tok", http).items(limit=3))
    assert [i.url for i in items] == ["https://outlook/1", "https://outlook/2", "https://outlook/3"]
    assert len({i.name for i in items}) == 3  # names stay unique across pages
    assert all(isinstance(i, Item) and i.name.endswith(".eml") for i in items)
    # the limit stops paging early: page 2 is never fetched when limit is 2
    assert len(list(Outlook("tok", graph({
        f"{G}/me/messages?$top=2&$select=id,webLink,lastModifiedDateTime": {
            "value": [{"id": "A1", "webLink": "u1"}, {"id": "A2", "webLink": "u2"}], "@odata.nextLink": p2},
        f"{G}/me/messages/A1/$value": b"x", f"{G}/me/messages/A2/$value": b"y"})).items(limit=2))) == 2


def test_sharepoint_site_drive_and_folder_path():
    site = "sites/s1/drive"
    http = graph({
        f"{G}/{site}/root:/Deals/Atlas:/children": {"value": [
            {"id": "f1", "name": "CIM.pdf", "file": {}, "webUrl": "https://sp/cim", "eTag": "e1"},
            {"id": "d1", "name": "Models", "folder": {}}]},
        f"{G}/{site}/items/d1/children": {"value": [{"id": "f2", "name": "lbo.xlsx", "file": {}, "webUrl": "https://sp/lbo", "eTag": "e2"}]},
        f"{G}/{site}/items/f1/content": b"%PDF",
        f"{G}/{site}/items/f2/content": b"xlsx",
    })
    items = list(OneDriveSharePoint("tok", http, drive=site, folder="Deals/Atlas").items())
    assert [(i.name, i.url, i.version) for i in items] == [
        ("CIM.pdf", "https://sp/cim", "e1"), ("Models/lbo.xlsx", "https://sp/lbo", "e2")]


def test_bad_graph_response_is_a_connector_error():
    with pytest.raises(ConnectorError, match="non-JSON"):
        list(Outlook("tok", lambda u, h: b"<html>throttled</html>").items())
    with pytest.raises(ConnectorError):
        Outlook("", graph({}))
