import json
from decimal import Decimal

from app import peers

FEED = (b'<feed><entry><company-info><cik>0000000001</cik><sic>7372</sic></company-info></entry>'
        b'<entry><company-info><cik>0000000002</cik><sic>2834</sic></company-info></entry></feed>')


def facts(name, end, val):
    return json.dumps({"entityName": name, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": end, "val": val, "form": "10-K", "fp": "FY", "accn": "0000000001-26-000001"}
    ]}}}}}).encode()


def test_sic_feed_keeps_only_the_requested_code():
    assert peers.sic_companies("7372", 1, lambda u: FEED) == ["0000000001"]


def test_peers_follow_size_and_recency_rule(monkeypatch):
    monkeypatch.setattr(peers.time, "sleep", lambda s: None)
    data = {"1": facts("Near Co", "2025-12-31", 1000), "3": facts("Old Co", "2019-12-31", 1000),
            "4": facts("Huge Co", "2025-12-31", 9000)}

    def facts_get(url):
        return data[url.split("CIK")[1].split(".")[0].lstrip("0")]
    out = peers.discover(Decimal(1000), "7372", set(), pages=1,
                         get=lambda u: b'<entry><company-info><cik>0000000001</cik><sic>7372</sic></company-info></entry>'
                         b'<entry><company-info><cik>0000000003</cik><sic>7372</sic></company-info></entry>'
                         b'<entry><company-info><cik>0000000004</cik><sic>7372</sic></company-info></entry>',
                         facts_get=facts_get)
    assert [p.name for p in out] == ["Near Co"] and out[0].period.startswith("FY2025")
    assert "SIC 7372" in out[0].rule
