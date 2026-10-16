import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.ratelimit import RateLimiter
from tests.helpers import new_tenant

ADMIN = {"X-Admin-Token": "test-admin"}


def test_key_rotation_and_revocation():
    c = TestClient(m.app)
    r = c.post("/admin/tenants", json={"name": "rot"}, headers=ADMIN).json()
    old = {"Authorization": f"Bearer {r['api_key']}"}
    new = c.post(f"/admin/tenants/{r['tenant_id']}/keys", headers=ADMIN).json()
    newh = {"Authorization": f"Bearer {new['api_key']}"}
    assert c.get("/documents", headers=old).status_code == 200
    assert c.get("/documents", headers=newh).status_code == 200
    assert c.delete(f"/admin/keys/{r['key_id']}", headers=ADMIN).status_code == 200
    assert c.get("/documents", headers=old).status_code == 401
    assert c.get("/documents", headers=newh).status_code == 200  # rotation: new key unaffected
    assert c.delete("/admin/keys/nonexistent", headers=ADMIN).status_code == 404
    assert c.delete(f"/admin/keys/{new['key_id']}").status_code == 403
    assert c.post("/admin/tenants/nope/keys", headers=ADMIN).status_code == 404


def test_rate_limiter_bucket_refills():
    rl = RateLimiter(60)  # 1 token/s, burst 60
    assert all(rl.allow("a", now=0.0) for _ in range(60))
    assert not rl.allow("a", now=0.0)
    assert rl.allow("b", now=0.0)  # other tenants unaffected
    assert not rl.allow("a", now=0.5)
    assert rl.allow("a", now=1.6)
    assert RateLimiter(0).allow("x")  # 0 disables


def test_api_returns_429_when_limited(monkeypatch):
    c = TestClient(m.app)
    h = new_tenant(c, "limited")
    monkeypatch.setattr(m, "limiter", RateLimiter(2))
    codes = [c.get("/documents", headers=h).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[-1] == 429


def test_upload_size_cap(monkeypatch):
    c = TestClient(m.app)
    h = new_tenant(c, "cap")
    monkeypatch.setattr(m, "MAX_UPLOAD", 100)
    r = c.post("/documents", files={"file": ("a.pdf", b"%PDF" + b"x" * 500, "application/pdf")}, headers=h)
    assert r.status_code == 413


CSV = "Company,Date,Shares,Price\nAcme Ltd,2024-03-01,100,1.50\nBeta plc,2024-04-02,50,2.00\n,,,\n"


def test_csv_ingest_rows_are_citable_and_idempotent():
    c = TestClient(m.app)
    h = new_tenant(c, "csv")
    r = c.post("/documents", files={"file": ("export.csv", ("﻿" + CSV).encode(), "text/csv")}, headers=h)
    assert r.status_code == 200
    doc = r.json()["id"]
    text = c.get(f"/documents/{doc}/pages/1", headers=h).json()["text"]
    assert "row 1: Company=Acme Ltd | Date=2024-03-01 | Shares=100 | Price=1.50" in text
    f = c.post("/facts", headers=h, json={
        "entity": "Acme Ltd", "metric": "shares_held", "period": "2024-03-01", "value": "100",
        "unit": "shares", "document_id": doc, "page": 1,
        "quote": "row 1: Company=Acme Ltd | Date=2024-03-01 | Shares=100"})
    assert f.status_code == 201
    again = c.post("/documents", files={"file": ("export.csv", CSV.encode(), "text/csv")}, headers=h)
    assert again.status_code == 200


@pytest.mark.parametrize("body", [b"only,header\n", b"single\ncolumn\nonly\n", b""])
def test_bad_csv_rejected_not_silently_accepted(body):
    c = TestClient(m.app)
    r = c.post("/documents", files={"file": ("x.csv", body, "text/csv")}, headers=new_tenant(c, "badcsv"))
    assert r.status_code == 422


def test_csv_pages_split_every_50_rows():
    rows = "\n".join(f"R{i},{i}" for i in range(120))
    c = TestClient(m.app)
    h = new_tenant(c, "csvbig")
    d = c.post("/documents", files={"file": ("big.csv", f"name,qty\n{rows}\n".encode(), "text/csv")},
               headers=h).json()
    assert d["n_pages"] == 3
