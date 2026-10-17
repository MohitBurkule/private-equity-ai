import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import SessionLocal, app
from app.models import FirmKnowledge, Target
from app.rls import bind_tenant

c = TestClient(app)


def tenant(name):
    t = c.post("/admin/tenants", json={"name": name}, headers={"X-Admin-Token": "test-admin"}).json()
    return {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]


def target(name, ref, sector, **kw):
    return {"name": name, "source": "manual", "source_ref": ref, "sector": sector, **kw}


def test_add_on_lists_same_sector_targets_minus_owned_and_passed():
    h, tid = tenant("ao1")
    co = c.post("/portfolio/companies", headers=h, json={"name": "Acme Software Ltd", "sector": "Software"}).json()["id"]
    c.post("/portfolio/companies", headers=h, json={"name": "Beta Holdings", "sector": "Software"})
    c.post("/targets", headers=h, json=[
        target("Zeta Analytics", "z", "Software"),
        target("Acme Software", "a", "Software"),
        target("Beta Holdings Inc", "b", "Software"),
        target("Quarry Co", "q", "Mining"),
        target("Nope Ltd", "n", None),
        target("Passed Co", "p", "Software"),
    ])
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.query(Target).filter_by(name="Passed Co").update({"status": "passed"})
        s.commit()
    r = c.get(f"/portfolio/companies/{co}/add-ons", headers=h).json()
    assert [i["name"] for i in r["items"]] == ["Zeta Analytics"]
    assert r["excluded_owned"] == 2 and r["rule"] is None
    assert c.get("/portfolio/companies/999999/add-ons", headers=h).status_code == 404


def test_add_on_applies_accepted_revenue_floor_and_flags_unknown_revenue():
    h, tid = tenant("ao2")
    co = c.post("/portfolio/companies", headers=h, json={"name": "Solo Ltd", "sector": "Software"}).json()["id"]
    c.post("/targets", headers=h, json=[
        target("Big Co", "big", "Software", revenue="30000000", revenue_url="https://example.com/big"),
        target("Small Co", "small", "Software", revenue="5000000", revenue_url="https://example.com/small"),
        target("Unknown Rev Co", "unk", "Software"),
    ])
    wb = Workbook()
    wb.active["A1"] = "Minimum revenue 20000000"
    buf = io.BytesIO()
    wb.save(buf)
    doc = c.post("/documents", files={"file": ("rule.xlsx", buf.getvalue(), "x")}, headers=h).json()["id"]
    with SessionLocal() as s:
        bind_tenant(s, tid)
        s.add(FirmKnowledge(tenant_id=tid, key="deal_screening_criteria", value="Sectors: software. Minimum revenue 20000000",
                            document_id=doc, page=1, quote="Minimum revenue 20000000", status="accepted"))
        s.commit()
    r = c.get(f"/portfolio/companies/{co}/add-ons", headers=h).json()
    by = {i["name"]: i for i in r["items"]}
    assert by["Big Co"]["verdict"] == "match" and "Small Co" not in by
    assert by["Unknown Rev Co"]["verdict"] == "review"
    assert r["rule"]["quote"] == "Minimum revenue 20000000"
