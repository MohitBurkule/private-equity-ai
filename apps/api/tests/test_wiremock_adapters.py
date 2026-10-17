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


def test_slack_channels_and_history_through_wiremock(wm):
    from app.connectors.slack import Slack

    http = rewrite_http({"https://slack.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/api/conversations.list"}, body=_json({"ok": True, "channels": [
        {"id": "C1", "name": "deal-atlas", "is_member": True}, {"id": "C2", "name": "x", "is_member": False}]}))
    wm.stub("GET", {"urlPath": "/api/conversations.history", "queryParameters": {"channel": {"equalTo": "C1"}}},
            body=_json({"ok": True, "messages": [
                {"type": "message", "ts": "1700.1", "user": "U1", "text": "EBITDA 300"},
                {"type": "message", "subtype": "channel_join", "ts": "1700.0", "user": "U2", "text": ""}]}))
    (item,) = list(Slack("tok", http, team="T1").items())
    assert item.name == "slack-deal-atlas.csv"
    assert item.data.count(b"\n") == 2  # header plus one message; the join event is dropped
    assert item.url == "https://app.slack.com/client/T1/C1"


def test_salesforce_soql_contacts_and_opportunities_through_wiremock(wm):
    from app.connectors.crm import Salesforce

    http = rewrite_http({"https://acme.my.salesforce.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/services/data/v60.0/query", "queryParameters": {"q": {"contains": "FROM Contact"}}},
            body=_json({"records": [
        {"Id": "003A", "Name": "Jane Doe", "Title": "CFO", "AccountId": "001A", "Email": "jane@acme.test",
         "attributes": {"type": "Contact"}}]}))
    wm.stub("GET", {"urlPath": "/services/data/v60.0/query", "queryParameters": {"q": {"contains": "FROM Opportunity"}}},
            body=_json({"records": [
        {"Id": "006A", "Name": "Atlas", "StageName": "IC", "Amount": 900, "CloseDate": "2026-12-01",
         "AccountId": "001A"}]}))
    conn = Salesforce("tok", http, instance_url="https://acme.my.salesforce.com", objects="Contact,Opportunity")
    items = list(conn.items())
    assert [i.name for i in items] == ["salesforce-Contact.csv", "salesforce-Opportunity.csv"]
    assert b"Jane Doe" in items[0].data and b"attributes" not in items[0].data
    assert items[1].url == "https://acme.my.salesforce.com/lightning/o/Opportunity/list"


def test_hubspot_deals_and_contacts_through_wiremock(wm):
    http = rewrite_http({"https://api.hubapi.com/": wm.base + "/"})
    wm.stub("GET", {"urlPath": "/crm/v3/objects/deals"}, body=_json({"results": [
        {"id": "d1", "properties": {"dealname": "Atlas", "amount": "900", "dealstage": "IC"}}]}))
    wm.stub("GET", {"urlPath": "/crm/v3/objects/contacts"}, body=_json({"results": [
        {"id": "c1", "properties": {"firstname": "Jane", "email": "jane@acme.test"}}]}))
    items = list(HubSpot("tok", http, portal="123", objects="deals,contacts").items())
    assert [i.external_id for i in items] == ["hubspot:deals", "hubspot:contacts"]
    assert items[0].data.splitlines()[0] == b"id,dealname,amount,dealstage"
    assert b"jane@acme.test" in items[1].data


def test_digest_posts_to_slack_and_teams_webhooks(wm):
    from app.chat_alerts import post_chat

    http = rewrite_http({"https://hooks.slack.com/": wm.base + "/", "https://outlook.office.com/": wm.base + "/"})
    wm.stub("POST", {"urlPath": "/services/T1/B1/xyz", "bodyPatterns": [{"contains": "[CRITICAL] Acme"}]},
            body="ok")
    wm.stub("POST", {"urlPath": "/webhookb2/abc/IncomingWebhook", "bodyPatterns": [{"contains": "[CRITICAL] Acme"}]},
            body="1")
    sent = post_chat("[IC daily] [CRITICAL] Acme: leverage breaches covenant",
                     slack_url="https://hooks.slack.com/services/T1/B1/xyz",
                     teams_url="https://outlook.office.com/webhookb2/abc/IncomingWebhook", http=http)
    assert sent == ["slack", "teams"]


def test_digest_refuses_unknown_webhook_hosts():
    from app.chat_alerts import post_chat

    with pytest.raises(ValueError, match="webhook"):
        post_chat("x", slack_url="https://evil.example.com/hook", http=lambda u, h: b"")
    with pytest.raises(ValueError, match="webhook"):
        post_chat("x", teams_url="http://outlook.office.com/webhook", http=lambda u, h: b"")
