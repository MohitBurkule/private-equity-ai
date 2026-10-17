"""Market-data vendors and mail connectors run end to end against WireMock (open-source jar).

Every response body below is SYNTHETIC: shaped from the public API documentation, with made-up prices, ids and
hosts. None of it is vendor data, and none of it comes from a licence. The adapters are not verified against
the live vendors (see app/marketvendors.py). Skipped unless WIREMOCK_JAR is set."""
import base64
import json
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from app.marketdata import Quote
from app.marketfeeds import FactSetProvider, from_env
from app.marketvendors import CapIQProvider, PitchBookProvider
from tests.helpers import new_tenant
from tests.mock_servers import WireMock, rewrite_http

c = TestClient(app)
CAPIQ = "https://capiq.synthetic.test/v2"
PITCHBOOK = "https://pitchbook.synthetic.test/api/v1"


@pytest.fixture(scope="module")
def wm():
    if not WireMock().available:
        pytest.skip("WIREMOCK_JAR not set")
    with WireMock() as w:
        yield w


def _prices(price: float, date: str) -> str:
    # SYNTHETIC price rows, shaped like the vendor price documents described in app/marketvendors.py
    return json.dumps({"data": [{"id": "SYN-1", "price": price, "currency": "usd", "date": "2026-10-01"},
                                {"id": "SYN-1", "price": price, "currency": "usd", "date": date}]})


def _eml(subject: str, body: str) -> bytes:
    e = EmailMessage()
    e["From"], e["To"], e["Subject"] = "synthetic.sender@example.test", "ic@example.test", subject
    e["Date"] = "Mon, 1 Jan 2024 10:00:00 +0000"
    e.set_content(body)
    return bytes(e)


def test_factset_capiq_pitchbook_quotes_through_wiremock(wm):
    wm.stub("GET", {"urlPath": "/content/factset-prices/v1/prices"},
            body=_prices(101.5, "2026-10-14"), headers={"Content-Type": "application/json"})
    wm.stub("GET", {"urlPath": "/v2/prices"}, body=_prices(55.25, "2026-10-15"),
            headers={"Content-Type": "application/json"})
    wm.stub("GET", {"urlPath": "/api/v1/prices"}, body=_prices(7.75, "2026-10-16"),
            headers={"Content-Type": "application/json"})
    fetch = rewrite_http({
        "https://api.factset.com/": wm.base + "/",
        "https://capiq.synthetic.test/": wm.base + "/",
        "https://pitchbook.synthetic.test/": wm.base + "/",
    })
    fs = FactSetProvider(username_serial="SYN-SERIAL", api_key="SYN-KEY", fetch=fetch).quote("SYN-1-US")
    cq = CapIQProvider(base_url=CAPIQ, token="SYN-TOKEN", fetch=fetch).quote("SYN-1")
    pb = PitchBookProvider(base_url=PITCHBOOK, token="SYN-TOKEN", fetch=fetch).quote("SYN-1")
    assert isinstance(fs, Quote) and fs.source == "factset" and fs.as_of == "2026-10-14"
    assert cq.source == "capiq" and str(cq.price) == "55.25" and cq.currency == "USD"
    assert pb.source == "pitchbook" and str(pb.price) == "7.75"


def test_from_env_builds_configured_vendors_on_the_mock(wm, monkeypatch):
    monkeypatch.setenv("CAPIQ_BASE_URL", CAPIQ)
    monkeypatch.setenv("CAPIQ_TOKEN", "SYN-TOKEN")
    monkeypatch.delenv("PITCHBOOK_BASE_URL", raising=False)
    monkeypatch.delenv("FACTSET_API_KEY", raising=False)
    fetch = rewrite_http({"https://capiq.synthetic.test/": wm.base + "/",
                          "https://query1.finance.yahoo.com/": wm.base + "/"})
    names = [p.name for p in from_env(fetch)]
    assert "capiq" in names and "pitchbook" not in names and "factset" not in names


def test_gmail_messages_ingested_and_each_cited_to_its_message(wm, monkeypatch):
    wm.stub("GET", {"urlPath": "/gmail/v1/users/me/messages"},
            body=json.dumps({"messages": [{"id": "syn-g1"}, {"id": "syn-g2"}]}),
            headers={"Content-Type": "application/json"})
    for mid in ("syn-g1", "syn-g2"):  # different bodies: identical content would dedupe to one document
        raw = base64.urlsafe_b64encode(_eml(f"SYNTHETIC Atlas CIM {mid}", f"SYNTHETIC revenue line {mid}.")).decode().rstrip("=")
        wm.stub("GET", {"urlPath": f"/gmail/v1/users/me/messages/{mid}"},
                body=json.dumps({"raw": raw, "internalDate": "1700"}), headers={"Content-Type": "application/json"})
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({"https://gmail.googleapis.com/": wm.base + "/"}))
    h = new_tenant(c, "vendor-gmail")
    out = c.post("/connectors/gmail/sync", json={"token": "tok", "deal": "atlas"}, headers=h).json()
    urls = sorted(d["source_url"] for d in out["ingested"])
    assert urls == ["https://mail.google.com/mail/u/0/#all/syn-g1", "https://mail.google.com/mail/u/0/#all/syn-g2"]
    for d in out["ingested"]:
        src = c.get(f"/documents/{d['document_id']}/source", headers=h).json()
        assert src["connector"] == "gmail" and src["url"] == d["source_url"]


def test_outlook_messages_ingested_and_each_cited(wm, monkeypatch):
    wm.stub("GET", {"urlPath": "/v1.0/me/messages"}, body=json.dumps({"value": [
        {"id": "AAA111syn", "webLink": "https://outlook.office.com/m/syn1", "lastModifiedDateTime": "t1"},
        {"id": "BBB222syn", "webLink": "https://outlook.office.com/m/syn2", "lastModifiedDateTime": "t2"}]}),
        headers={"Content-Type": "application/json"})
    for mid in ("AAA111syn", "BBB222syn"):
        wm.stub("GET", {"urlPath": f"/v1.0/me/messages/{mid}/$value"}, body=_eml(f"SYNTHETIC IOI {mid}", "SYNTHETIC body."),
                headers={"Content-Type": "message/rfc822"})
    monkeypatch.setattr(m, "CONNECTOR_HTTP", rewrite_http({"https://graph.microsoft.com/": wm.base + "/"}))
    h = new_tenant(c, "vendor-outlook")
    out = c.post("/connectors/outlook/sync", json={"token": "tok", "deal": "atlas"}, headers=h).json()
    urls = sorted(d["source_url"] for d in out["ingested"])
    assert urls == ["https://outlook.office.com/m/syn1", "https://outlook.office.com/m/syn2"]
