import io
import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import SessionLocal, app, llm_dependency
from app.models import Deal
from app.rls import bind_tenant

c = TestClient(app)


class Fake:
    def __init__(self, values):
        self.values = values

    def complete(self, system, prompt):
        return json.dumps({"values": self.values})


def old(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def accept_rule(h, text, key):
    wb = Workbook()
    wb.active["A1"] = text
    b = io.BytesIO()
    wb.save(b)
    doc = c.post("/documents", files={"file": ("policy.xlsx", b.getvalue(), "x")}, headers=h).json()["id"]
    app.dependency_overrides[llm_dependency] = lambda: Fake([{"key": key, "value": text, "page": 1, "quote": text}])
    try:
        r = c.post("/firm-knowledge/extract", headers=h, json={"document_id": doc}).json()
    finally:
        app.dependency_overrides.pop(llm_dependency)
    assert len(r["saved"]) == 1, r["rejected"]
    c.post(f"/firm-knowledge/{r['saved'][0]['id']}/review", headers=h, json={"status": "accepted"})


def backdate(h_tenant, name, days):
    with SessionLocal() as s:
        bind_tenant(s, h_tenant)
        s.query(Deal).filter_by(name=name).one().updated_at = old(days)
        s.commit()


def test_accepted_stall_rule_replaces_the_default_threshold():
    t = c.post("/admin/tenants", json={"name": "fd1"}, headers={"X-Admin-Token": "test-admin"}).json()
    h, tid = {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]
    c.post("/deals", headers=h, json={"name": "FD1 Slow Deal"})
    backdate(tid, "FD1 Slow Deal", 15)
    assert [a for a in c.post("/alerts/scan", headers=h).json()["created"] if "FD1 Slow" in a["title"]] == []  # 30-day default
    accept_rule(h, "Live deals must be updated within 10 days", "deal_stall_days")
    made = [a for a in c.post("/alerts/scan", headers=h).json()["created"] if "FD1 Slow" in a["title"]]
    assert len(made) == 1 and "15 days" in made[0]["title"]


def test_zero_or_missing_rule_falls_back_to_default():
    t = c.post("/admin/tenants", json={"name": "fd2"}, headers={"X-Admin-Token": "test-admin"}).json()
    h, tid = {"Authorization": f"Bearer {t['api_key']}"}, t["tenant_id"]
    c.post("/deals", headers=h, json={"name": "FD2 Old Deal"})
    backdate(tid, "FD2 Old Deal", 40)
    accept_rule(h, "Deal stall days: 0", "deal_stall_days")  # 0 is not a usable threshold
    made = [a for a in c.post("/alerts/scan", headers=h).json()["created"] if "FD2 Old" in a["title"]]
    assert len(made) == 1 and "40 days" in made[0]["title"]
