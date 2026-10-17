from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import Alert
from app.rls import bind_tenant

c = TestClient(app)


def add(tid, kind, sev, created, n):
    return Alert(tenant_id=tid, kind=kind, severity=sev, title=f"t{n}", detail="d", dedupe_key=f"k{n}",
                 fact_ids="[1]", status="new", created_at=created)


def test_brief_counts_since_and_puts_critical_first():
    t = c.post("/admin/tenants", json={"name": "brief2"}, headers={"X-Admin-Token": "test-admin"}).json()
    h = {"Authorization": f"Bearer {t['api_key']}"}
    with SessionLocal() as s:
        bind_tenant(s, t["tenant_id"])
        s.add_all([add(t["tenant_id"], "covenant", "warning", "2026-10-10T00:00:00+00:00", 1),
                   add(t["tenant_id"], "covenant", "critical", "2026-10-17T01:00:00+00:00", 2),
                   add(t["tenant_id"], "kpi", "warning", "2026-10-16T09:00:00+00:00", 3),
                   add(t["tenant_id"], "filing", "info", "2026-10-17T02:00:00+00:00", 4)])
        s.commit()
    b = c.get("/alerts/brief", params={"since": "2026-10-15T00:00:00+00:00"}, headers=h).json()
    assert b["total"] == 3
    assert b["by_kind"] == {"covenant": 1, "kpi": 1, "filing": 1}
    assert b["by_severity"] == {"critical": 1, "warning": 1, "info": 1}
    assert [a["severity"] for a in b["top"]] == ["critical", "warning", "info"]
    assert b["top"][0]["title"] == "t2" and b["top"][0]["fact_ids"] == [1]
