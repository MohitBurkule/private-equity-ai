from decimal import Decimal

from fastapi.testclient import TestClient

from app import peers as peers_mod
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def add(h, body):
    assert c.post("/targets", headers=h, json=[body]).status_code == 201
    return next(t["id"] for t in c.get("/targets", headers=h).json()["items"] if t["name"] == body["name"])


def test_sic_peers_route_lists_peers_with_rule_and_median(monkeypatch):
    h = new_tenant(c, "sicpeers")
    tid = add(h, {"name": "Acme", "source": "manual", "source_ref": "A1", "sic": "7372", "revenue": "100",
                  "revenue_url": "https://example.test/acme"})
    seen = {}

    def fake(rev, sic, exclude, pages=1, **kw):
        seen.setdefault("sic", sic)  # first call is the exact code; widening may follow
        seen.setdefault("rev", rev)
        seen.setdefault("exclude", exclude)
        if sic != "7372":  # the family widening asks for other codes; this stub has peers for the exact code only
            return []
        return [peers_mod.Peer("0000000002", Decimal(120), "FY2024", "https://sec.gov/x", "SIC 7372", "Beta"),
                peers_mod.Peer("0000000003", Decimal(80), "FY2024", "https://sec.gov/y", "SIC 7372", "Gamma")]

    monkeypatch.setattr(peers_mod, "discover", fake)
    r = c.get(f"/targets/{tid}/sic-peers", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert seen["sic"] == "7372" and seen["rev"] == Decimal(100)
    assert body["peers"] == 2 and body["median"] == "100.0"
    assert body["items"][0]["rule"] == "SIC 7372"


def test_sic_peers_needs_sic_and_revenue_and_tenant(monkeypatch):
    h = new_tenant(c, "sicpeers2")
    tid = add(h, {"name": "NoSic", "source": "manual", "source_ref": "N1"})
    body = c.get(f"/targets/{tid}/sic-peers", headers=h).json()
    assert body["peers"] == [] and "needs a SIC" in body["note"]
    other = new_tenant(c, "sicpeers3")
    assert c.get(f"/targets/{tid}/sic-peers", headers=other).status_code == 404
