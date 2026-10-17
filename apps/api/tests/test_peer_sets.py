import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app import peers as peers_mod
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def entry(cik, sic):
    return f"<entry><company-info><cik>{cik}</cik><sic>{sic}</sic></company-info></entry>".encode()


def facts(name, end, val):
    return {"entityName": name, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2025-01-01", "end": end, "val": val, "form": "10-K", "fp": "FY", "accn": "0000000001-26-000001"}
    ]}}}}}


def test_group_widening_only_when_exact_code_is_thin(monkeypatch):
    monkeypatch.setattr(peers_mod.time, "sleep", lambda s: None)
    feeds = {"7372": entry("0000000011", "7372"), "7371": entry("0000000012", "7371"),
             "7374": entry("0000000013", "7374")}
    data = {"11": facts("Exact Co", "2025-12-31", 1000), "12": facts("Group Co", "2025-12-31", 1100),
            "13": facts("Other Group Co", "2025-12-31", 900)}

    def get(url):
        code = url.split("SIC=")[1].split("&")[0]
        return feeds.get(code, b"")

    def facts_get(url):
        return json.dumps(data[url.split("CIK")[1].split(".")[0].lstrip("0")]).encode()

    out = peers_mod.discover_with_group(Decimal(1000), "7372", set(), pages=1, min_peers=3, get=get,
                                        facts_get=facts_get)
    assert [(p.name, p.matched_on) for p in out] == [
        ("Exact Co", "sic"), ("Group Co", "sic_group"), ("Other Group Co", "sic_group")]
    assert "SIC family 737" in out[1].rule
    # enough exact-code peers: no widening
    out = peers_mod.discover_with_group(Decimal(1000), "7372", set(), pages=1, min_peers=1, get=get,
                                        facts_get=facts_get)
    assert [p.matched_on for p in out] == ["sic"]


def test_peer_set_save_list_refresh_and_tenant_isolation(monkeypatch):
    h = new_tenant(c, "peerset")
    other = new_tenant(c, "peerset2")
    assert c.post("/deals", headers=h, json={"name": "Project Lake"}).status_code in (200, 201)
    assert c.post("/targets", headers=h, json=[{"name": "Lake Target", "source": "sec", "source_ref": "0000000099",
                                                 "sic": "7372", "revenue": "1000",
                                                 "revenue_url": "https://example.test/t"}]).status_code == 201
    tid = next(t["id"] for t in c.get("/targets?q=Lake", headers=h).json()["items"])
    monkeypatch.setattr(peers_mod, "discover_with_group", lambda *a, **k: [
        peers_mod.Peer("0000000021", Decimal(900), "FY2025", "https://sec.gov/p", "SIC 7372", "Peer A")])
    r = c.post("/deals/Project Lake/peer-sets", headers=h, json={"target_id": tid, "name": "Core"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["items"][0]["name"] == "Peer A"
    assert c.get("/deals/Project Lake/peer-sets", headers=h).json()[0]["name"] == "Core"

    # refresh: peer A still has revenue, peer B has none now and is dropped with its reason
    monkeypatch.setattr(peers_mod.edgar, "fetch_companyfacts", lambda cik, get=None: (
        facts("Peer A Renamed", "2025-12-31", 950) if cik.lstrip("0") == "21" else {"entityName": "B", "facts": {}}))
    monkeypatch.setattr(peers_mod.time, "sleep", lambda s: None)
    body = c.post(f"/deals/Project Lake/peer-sets/{sid}/refresh", headers=h).json()
    assert body["items"][0]["revenue"] == "950" and body["items"][0]["name"] == "Peer A Renamed"
    assert body["dropped"] == []
    monkeypatch.setattr(peers_mod.edgar, "fetch_companyfacts", lambda cik, get=None: {"entityName": "B", "facts": {}})
    body = c.post(f"/deals/Project Lake/peer-sets/{sid}/refresh", headers=h).json()
    assert body["items"] == [] and body["dropped"][0]["reason"] == "no current 10-K revenue"

    assert c.get("/deals/Project Lake/peer-sets", headers=other).status_code == 404
    assert c.post(f"/deals/Project Lake/peer-sets/{sid}/refresh", headers=other).status_code == 404


def test_peer_refresh_workflow_runs_on_schedule(monkeypatch):
    from datetime import UTC, datetime

    from app import workflows as wf
    from app.main import SessionLocal
    from app.models import PeerSet
    from app.rls import bind_tenant

    h = new_tenant(c, "peerwf")
    tid = h["Authorization"]  # tenant id is not in the key header; look it up from a listed target instead
    with SessionLocal() as s:
        from app.models import Tenant
        tid = s.query(Tenant).order_by(Tenant.id.desc()).first().id
        bind_tenant(s, tid)
        s.add(PeerSet(tenant_id=tid, deal="D", name="Wf", target_id=1,
                      items=json.dumps([{"cik": "0000000031", "name": "X", "revenue": "1", "period": "FY2025",
                                         "source_url": "u", "rule": "r", "matched_on": "sic"}]),
                      dropped="[]", refreshed_at="", created_by="t", created_at=""))
        s.commit()
        row = s.query(PeerSet).filter_by(tenant_id=tid, name="Wf").one()
        monkeypatch.setattr(peers_mod.edgar, "fetch_companyfacts", lambda cik, get=None: facts("X", "2025-12-31", 2))
        monkeypatch.setattr(peers_mod.time, "sleep", lambda s_: None)
        wf.create(s, tid, "peers", "peer_refresh", 7, {"peer_set_id": row.id}, ["ops@example.com"],
                  start=datetime(2026, 10, 17, tzinfo=UTC))
        sent = []
        wf.run_due(s, tid, None, mailer=lambda to, subj, body: sent.append(body),
                   now=datetime(2026, 10, 17, tzinfo=UTC))
        assert sent and "Peer set Wf: 1 kept, 0 dropped." in sent[0]
