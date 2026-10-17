"""Outlook, Drive and HubSpot adapters run unchanged against WireMock (open source, runs from its jar).
Skipped unless WIREMOCK_JAR points at wiremock-standalone. Each stub mirrors the documented API shape."""
import json

import pytest

from app.connectors.crm import HubSpot
from app.connectors.files import GoogleDrive
from app.connectors.graph import Outlook
from tests.mock_servers import WireMock, rewrite_http

pytestmark = pytest.mark.skipif(not WireMock().available, reason="WIREMOCK_JAR not set")


@pytest.fixture(scope="module")
def wm():
    with WireMock() as w:
        yield w


def _json(body):
    return json.dumps(body)


def test_outlook_pages_and_downloads_through_wiremock(wm):
    http = rewrite_http({"https://graph.microsoft.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/v1.0/me/messages"}, body=_json({"value": [
        {"id": "AAA111bbb222", "webLink": "https://outlook.office.com/m/1", "lastModifiedDateTime": "t1"}]}),
        headers={"Content-Type": "application/json"})
    wm.stub("GET", {"urlPath": "/v1.0/me/messages/AAA111bbb222/$value"}, body=b"From: ceo@acme.test\r\n\r\nhi",
            headers={"Content-Type": "message/rfc822"})
    (item,) = list(Outlook("tok", http).items(limit=1))
    assert item.url == "https://outlook.office.com/m/1"
    assert item.data.startswith(b"From: ceo@acme.test")


def test_drive_folder_listing_and_download_through_wiremock(wm):
    http = rewrite_http({"https://www.googleapis.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/drive/v3/files", "queryParameters": {"q": {"contains": "root"}}},
            body=_json({"files": [{"id": "p1", "name": "Teaser.pdf", "mimeType": "application/pdf",
                                   "webViewLink": "https://drive.google.com/file/d/p1/view"}]}))
    wm.stub("GET", {"urlPath": "/drive/v3/files/p1", "queryParameters": {"alt": {"equalTo": "media"}}},
            body=b"%PDF-1.4")
    (item,) = list(GoogleDrive("tok", http).items(limit=1))
    assert item.name == "Teaser.pdf" and item.data == b"%PDF-1.4"
    assert item.url == "https://drive.google.com/file/d/p1/view"


def test_hubspot_companies_through_wiremock(wm):
    http = rewrite_http({"https://api.hubapi.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/crm/v3/objects/companies"}, body=_json({"results": [
        {"id": "9", "properties": {"name": "Acme", "domain": "acme.test"}}]}))
    (item,) = list(HubSpot("tok", http, portal="123", objects="companies").items())
    assert item.data.splitlines()[0] == b"id,name,domain"
    assert item.url == "https://app.hubspot.com/contacts/123/objects/companies"
