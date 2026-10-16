"""Header layouts are SYNTHETIC (no real PitchBook/Crowdcube/Seedrs export was available)."""
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)

PB = (b"Companies,Last Financing Date,Post Valuation (GBP mm),Total Raised\n"
      b"Acme Ltd,2025-03-01,45.5,\"\xc2\xa312,000,000\"\n"
      b"Beta Ltd,2025-01-01,10,5000000\n")
CC = b"Company,Date,Amount invested,Shares,Currency\nAcme,2024-05-02,\"1,500\",300,GBP\n"


def up(h, data, name):
    r = c.post("/documents", files={"file": (name, data, "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_pitchbook_preview_then_commit_with_scale_and_rejects():
    h = new_tenant(c, "vf1")
    d = up(h, PB, "pb.csv")
    prev = c.post(f"/documents/{d}/vendor-facts", params={"preset": "pitchbook"}, headers=h).json()
    assert not prev["committed"]
    pm = next(f for f in prev["facts"] if f["metric"] == "post_money_valuation")
    assert pm["value"] == "45500000.0" and pm["unit"] == "GBP" and pm["quote"] == "Post Valuation (GBP mm)=45.5"
    assert {r["row"] for r in prev["rejected"]} == {2}  # Beta: no currency anywhere
    assert c.get("/facts", headers=h).json() == []  # preview stores nothing
    out = c.post(f"/documents/{d}/vendor-facts", params={"preset": "pitchbook", "commit": True}, headers=h).json()
    assert not out["refused"] and all(f["status"] for f in out["facts"])
    got = c.get("/facts", params={"entity": "Acme Ltd"}, headers=h).json()
    assert {f["metric"] for f in got} == {"post_money_valuation", "total_raised"}
    assert got[0]["sources"][0]["quote"]


def test_currency_override_and_crowdcube_columns():
    h = new_tenant(c, "vf2")
    d = up(h, PB, "pb2.csv")
    out = c.post(f"/documents/{d}/vendor-facts", params={"preset": "pitchbook", "currency": "usd"}, headers=h).json()
    assert {f["entity"] for f in out["facts"]} == {"Acme Ltd", "Beta Ltd"} and not out["rejected"]
    d2 = up(h, CC, "cc.csv")
    cc = c.post(f"/documents/{d2}/vendor-facts", params={"preset": "crowdcube", "commit": True}, headers=h).json()
    m = {f["metric"]: f for f in cc["facts"]}
    assert m["investment_amount"]["value"] == "1500" and m["shares_held"]["unit"] == "shares"


def test_errors_and_isolation():
    h = new_tenant(c, "vf3")
    d = up(h, PB, "pb3.csv")
    assert c.post(f"/documents/{d}/vendor-facts", params={"preset": "nope"}, headers=h).status_code == 422
    other = new_tenant(c, "vf4")
    assert c.post(f"/documents/{d}/vendor-facts", params={"preset": "pitchbook"}, headers=other).status_code == 404
    assert c.post(f"/documents/{d}/vendor-facts", params={"preset": "pitchbook"}).status_code == 401
