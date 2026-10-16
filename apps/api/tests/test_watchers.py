from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import SessionLocal, app
from app.models import DDRequest, Deal
from tests.helpers import new_tenant

c = TestClient(app)


def old(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")



def test_stalled_deal_and_overdue_dd_alerts_once_per_week_and_skip_closed():
    h = new_tenant(c, "wt1")
    for n in ("WT1 Atlas", "WT1 Borealis", "WT1 Closed Co"):
        c.post("/deals", headers=h, json={"name": n})
    c.post("/dd/requests/seed", headers=h, json={"deal": "WT1 Atlas", "categories": ["legal"]})
    with SessionLocal() as s:
        tid = s.query(Deal).filter_by(name="WT1 Atlas").one().tenant_id
        from app.rls import bind_tenant
        bind_tenant(s, tid)
        s.query(Deal).filter_by(name="WT1 Atlas").one().updated_at = old(45)
        s.query(Deal).filter_by(name="WT1 Closed Co").one().updated_at = old(90)
        s.query(Deal).filter_by(name="WT1 Closed Co").one().stage = "closed"
        for r in s.query(DDRequest).filter_by(deal="WT1 Atlas"):
            r.updated_at = old(20)
        s.commit()
    made = c.post("/alerts/scan", headers=h).json()["created"]
    titles = sorted(a["title"] for a in made)
    assert len(titles) == 2 and titles[0].startswith("WT1 Atlas: ") and "DD request" in titles[0] + titles[1]
    assert not any("WT1 Borealis" in t or "WT1 Closed Co" in t for t in titles)
    assert c.post("/alerts/scan", headers=h).json()["created"] == []
